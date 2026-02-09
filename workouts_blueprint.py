from flask import Blueprint, jsonify, request, g
from db_helpers import get_db_connection
import psycopg2
import psycopg2.extras
from auth_middleware import token_required
from db_helpers import get_db_connection, consolidate_comments_in_workouts


hoots_blueprint = Blueprint('hoots_blueprint', __name__)

@hoots_blueprint.route('/workouts', methods=['POST'])
@token_required
def create_workout():
    try:
        new_workout = request.get_json()
        new_workout["author"] = g.user["id"]
        exercises = new_workout.pop("exercises", [])  # extract exercises if any

        connection = get_db_connection()
        cursor = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # create workout
        cursor.execute("""
            INSERT INTO workouts (author, name, description, workout_type, difficulty)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (
            new_workout["author"],
            new_workout["name"],
            new_workout["description"],
            new_workout["workout_type"],
            new_workout["difficulty"]
        ))
        workout_id = cursor.fetchone()["id"]

        # add exercises into join table
        for exercise in exercises:
            cursor.execute("""
                INSERT INTO workout_exercises (workout_id, exercise_id, sets, reps)
                VALUES (%s, %s, %s, %s)
            """, (
                workout_id,
                exercise["id"],
                exercise.get("sets"),
                exercise.get("reps")
            ))

        # grab with author username
        cursor.execute("""
            SELECT w.id,
                   w.author AS workout_author_id,
                   w.name,
                   w.description,
                   w.workout_type,
                   w.difficulty,
                   u_workout.username AS author_username
            FROM workouts w
            JOIN users u_workout ON w.author = u_workout.id
            WHERE w.id = %s
        """, (workout_id,))

        created_workout = cursor.fetchone()

        # fetch the exercises
        cursor.execute("""
            SELECT e.id, e.name, e.muscle_group, e.equipment, we.sets, we.reps
            FROM exercises e
            JOIN workout_exercises we ON e.id = we.exercise_id
            WHERE we.workout_id = %s
        """, (workout_id,))
        exercises = cursor.fetchall()
        # add exercises
        created_workout["exercises"] = exercises

        # initialize comments
        created_workout["comments"] = []

        connection.commit()
        connection.close()
        return jsonify(created_workout), 201

    except Exception as error:
        return jsonify({"error": str(error)}), 500


@hoots_blueprint.route('/workouts', methods=['GET'])
def workouts_index():
    try:
        connection = get_db_connection()
        cursor = connection.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor
        )
        cursor.execute("""
            SELECT w.id,
                   w.author AS workout_author_id,
                   w.name,
                   w.description,
                   w.workout_type,
                   w.difficulty,
                   u_workout.username AS author_username
            FROM workouts w
            INNER JOIN users u_workout ON w.author = u_workout.id;
            LEFT JOIN comments c ON w.id = c.workout
            LEFT JOIN users u_comment ON c.author = u_comment.id;
        """)
        workouts = cursor.fetchall()
        consolidated_workouts = consolidate_comments_in_workouts(workouts)
        connection.commit()
        connection.close()
        return jsonify(consolidated_workouts), 200
    except Exception as error:
        return jsonify({"error": str(error)}), 500


@hoots_blueprint.route('/workouts/<workout_id>', methods=['GET'])
def show_workout(workout_id):
    try:
        connection = get_db_connection()
        cursor = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # workout & comments
        cursor.execute("""
            SELECT w.id,
                   w.author AS workout_author_id,
                   w.name,
                   w.description,
                   w.workout_type,
                   w.difficulty,
                   u_workout.username AS author_username,
                   c.id AS comment_id,
                   c.text AS comment_text,
                   u_comment.username AS comment_author_username
            FROM workouts w
            JOIN users u_workout ON w.author = u_workout.id
            LEFT JOIN comments c ON w.id = c.workout
            LEFT JOIN users u_comment ON c.author = u_comment.id
            WHERE w.id = %s
        """, (workout_id,))
        unprocessed_workout = cursor.fetchall()  # all comments but repeating workout

        if not unprocessed_workout:
            connection.close()
            return jsonify({"error": "Workout not found"}), 404

        
        nested_workouts = consolidate_comments_in_workouts(unprocessed_workout)

        # get exercises
        cursor.execute("""
            SELECT e.id, e.name, e.muscle_group, e.equipment, we.sets, we.reps
            FROM exercises e
            JOIN workout_exercises we ON e.id = we.exercise_id
            WHERE we.workout_id = %s
        """, (workout_id,))
        exercises = cursor.fetchall()

        # attach to the consolidated workout
        processed_workout = nested_workouts[0]
        processed_workout["exercises"] = exercises

        connection.close()
        return jsonify(processed_workout), 200

    except Exception as error:
        return jsonify({"error": str(error)}), 500

@hoots_blueprint.route('/workouts/<workout_id>', methods=['PUT']) #check when testing
@token_required
def update_workout(workout_id):
    try:
        updated_data = request.json
        exercises = updated_data.pop("exercises", [])  # exercises from frontend

        connection = get_db_connection()
        cursor = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1️⃣ Check workout exists
        cursor.execute("SELECT * FROM workouts WHERE id = %s", (workout_id,))
        workout = cursor.fetchone()
        if workout is None:
            connection.close()
            return jsonify({"error": "Workout not found"}), 404

        # 2️⃣ Authorization
        if workout["author"] != g.user["id"]:
            connection.close()
            return jsonify({"error": "Unauthorized"}), 401

        # 3️⃣ Update workout main fields
        cursor.execute("""
            UPDATE workouts
            SET name = %s, description = %s, workout_type = %s, difficulty = %s
            WHERE id = %s
        """, (
            updated_data["name"],
            updated_data["description"],
            updated_data["workout_type"],
            updated_data["difficulty"],
            workout_id
        ))

        # 4️⃣ Fetch current exercises for this workout
        cursor.execute("""
            SELECT exercise_id FROM workout_exercises
            WHERE workout_id = %s
        """, (workout_id,))
        current_ex_ids = {row["exercise_id"] for row in cursor.fetchall()}

        # 5️⃣ Build sets of new exercises
        updated_ex_ids = {ex["id"] for ex in exercises}

        # 6️⃣ Delete exercises removed in frontend
        to_delete = current_ex_ids - updated_ex_ids
        if to_delete:
            cursor.execute("""
                DELETE FROM workout_exercises
                WHERE workout_id = %s AND exercise_id = ANY(%s)
            """, (workout_id, list(to_delete)))

        # 7️⃣ Update or insert exercises
        for ex in exercises:
            cursor.execute("""
                UPDATE workout_exercises
                SET sets = %s, reps = %s
                WHERE workout_id = %s AND exercise_id = %s
                RETURNING *
            """, (
                ex.get("sets"),
                ex.get("reps"),
                workout_id,
                ex["id"]
            ))
            updated_exercise = cursor.fetchone()

            # insert new if not exists
            if not updated_exercise:
                cursor.execute("""
                    INSERT INTO workout_exercises (workout_id, exercise_id, sets, reps)
                    VALUES (%s, %s, %s, %s)
                """, (
                    workout_id,
                    ex["id"],
                    ex.get("sets"),
                    ex.get("reps")
                ))

        # 8️⃣ Fetch updated workout
        cursor.execute("""
            SELECT w.id,
                   w.author AS workout_author_id,
                   w.name,
                   w.description,
                   w.workout_type,
                   w.difficulty,
                   u_workout.username AS author_username
            FROM workouts w
            JOIN users u_workout ON w.author = u_workout.id
            WHERE w.id = %s
        """, (workout_id,))
        updated_workout = cursor.fetchone()

        # 9️⃣ Fetch updated exercises
        cursor.execute("""
            SELECT e.id, e.name, e.muscle_group, e.equipment, we.sets, we.reps
            FROM exercises e
            JOIN workout_exercises we ON e.id = we.exercise_id
            WHERE we.workout_id = %s
        """, (workout_id,))
        updated_workout["exercises"] = cursor.fetchall()

        #  🔟 Keep comments untouched
        updated_workout["comments"] = []

        connection.commit()
        connection.close()

        return jsonify(updated_workout), 200

    except Exception as error:
        return jsonify({"error": str(error)}), 500

# @hoots_blueprint.route('/workouts/<workout_id>', methods=['PUT'])
# @token_required
# def update_workout(workout_id):
#     try:
#         updated_workout_data = request.json

#         connection = get_db_connection()
#         cursor = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

#         # workout to update
#         cursor.execute("SELECT * FROM workouts WHERE id = %s", (workout_id,))
#         workout_to_update = cursor.fetchone()

#         if workout_to_update is None:
#             connection.close()
#             return jsonify({"error": "Workout not found"}), 404

#         #  authorization
#         if workout_to_update["author"] != g.user["id"]:
#             connection.close()
#             return jsonify({"error": "Unauthorized"}), 401

#         # updating
#         cursor.execute("""
#             UPDATE workouts 
#             SET name = %s, description = %s, workout_type = %s, difficulty = %s
#             WHERE id = %s
#             RETURNING id
#         """, (
#             updated_workout_data["name"],
#             updated_workout_data["description"],
#             updated_workout_data["workout_type"],
#             updated_workout_data["difficulty"],
#             workout_id
#         ))

#         updated_workout_id = cursor.fetchone()["id"]

#         # get the updated workout with username
#         cursor.execute("""
#             SELECT w.id,
#                    w.author AS workout_author_id,
#                    w.name,
#                    w.description,
#                    w.workout_type,
#                    w.difficulty,
#                    u_workout.username AS author_username
#             FROM workouts w
#             JOIN users u_workout ON w.author = u_workout.id
#             WHERE w.id = %s
#         """, (updated_workout_id,))

#         updated_workout = cursor.fetchone()

#         connection.commit()
#         connection.close()

#         return jsonify(updated_workout), 200

#     except Exception as error:
#         return jsonify({"error": str(error)}), 500

@hoots_blueprint.route('/workouts/<workout_id>', methods=['DELETE'])
@token_required
def delete_workout(workout_id):
    try:
        connection = get_db_connection()
        cursor = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # workout to delete
        cursor.execute("SELECT * FROM workouts WHERE id = %s", (workout_id,))
        workout_to_delete = cursor.fetchone()

        if workout_to_delete is None:
            connection.close()
            return jsonify({"error": "Workout not found"}), 404

        #  authorization
        if workout_to_delete["author"] != g.user["id"]:
            connection.close()
            return jsonify({"error": "Unauthorized"}), 401

        # delete
        cursor.execute("DELETE FROM workouts WHERE id = %s", (workout_id,))

        connection.commit()
        connection.close()

        #  deleted workout info
        return jsonify(workout_to_delete), 200

    except Exception as error:
        return jsonify({"error": str(error)}), 500


