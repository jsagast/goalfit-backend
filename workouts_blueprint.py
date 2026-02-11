from flask import Blueprint, jsonify, request, g
from db_helpers import get_db_connection
import psycopg2
import psycopg2.extras
from auth_middleware import token_required
from db_helpers import get_db_connection, consolidate_comments_in_workouts


workouts_blueprint = Blueprint('workouts_blueprint', __name__)

@workouts_blueprint.route('/workouts', methods=['POST'])
@token_required
def create_workout():
    try:
        new_workout = request.get_json()
        print(new_workout)
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
        print (exercises)
        for exercise in exercises:
            cursor.execute("""
                INSERT INTO workout_exercises (workout_id, exercise_id, sets, reps)
                VALUES (%s, %s, %s, %s)
            """, (
                workout_id,
                exercise["exercise_id"],
                int(exercise.get("sets") or 0),
                int(exercise.get("reps") or 0)
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
        print(error)
        return jsonify({"error": str(error)}), 500


@workouts_blueprint.route('/workouts', methods=['GET'])
def workouts_index():
    try:
        connection = get_db_connection()
        cursor = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute("""
            SELECT 
                w.id,
                w.author AS workout_author_id,
                w.name,
                w.description,
                w.workout_type,
                w.difficulty,
                u_workout.username AS author_username,
                w.created_at,
                c.id AS comment_id,
                c.text AS comment_text,
                u_comment.username AS comment_author_username
            FROM workouts w
            INNER JOIN users u_workout ON w.author = u_workout.id
            LEFT JOIN comments c ON w.id = c.workout_id
            LEFT JOIN users u_comment ON c.author = u_comment.id;
        """)
        workouts = cursor.fetchall()
        consolidated_workouts = consolidate_comments_in_workouts(workouts)
        connection.commit()
        connection.close()
        return jsonify(consolidated_workouts), 200
    except Exception as error:
        print(error)
        return jsonify({"error": str(error)}), 500


@workouts_blueprint.route('/workouts/<workout_id>', methods=['GET'])
def show_workout(workout_id):
    try:
        connection = get_db_connection()
        cursor = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # workout & comments
        cursor.execute("""
            SELECT 
                w.id,
                w.author AS workout_author_id,
                w.name,
                w.description,
                w.workout_type,
                w.difficulty,
                u_workout.username AS author_username,
                w.created_at,
                c.id AS comment_id,
                c.text AS comment_text,
                u_comment.username AS comment_author_username
            FROM workouts w
            JOIN users u_workout ON w.author = u_workout.id
            LEFT JOIN comments c ON w.id = c.workout_id
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

@workouts_blueprint.route('/workouts/<workout_id>', methods=['PUT']) 
@token_required
def update_workout(workout_id):
    try:
        updated_data = request.json
        exercises = updated_data.pop("exercises", [])  #remove first to repeat create op.

        connection = get_db_connection()
        cursor = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # I'm looking for workouts
        cursor.execute("SELECT * FROM workouts WHERE id = %s", (workout_id,))
        workout = cursor.fetchone()
        if workout is None:
            connection.close()
            return jsonify({"error": "Workout not found"}), 404

        # authorization for author to edit
        if workout["author"] != g.user["id"]:
            connection.close()
            return jsonify({"error": "Unauthorized"}), 401

        #  to update workout db
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

        # grabbing the exercises from join table workout_exercises
        cursor.execute("""
            SELECT exercise_id FROM workout_exercises
            WHERE workout_id = %s
        """, (workout_id,))

        # I do this to get access to all exercises part of the same workout (cursor.fetch all is containing all row that were found)
        current_ex_ids = {row["exercise_id"] for row in cursor.fetchall()}

        # do the same with updated exercises (the ones I separate when receiving info)
        updated_ex_ids = {ex["exercise_id"] for ex in exercises}

        # delete from db the exercises that are not part of received info (a but not b)
        to_delete = current_ex_ids - updated_ex_ids
        if to_delete:
            cursor.execute("""
                DELETE FROM workout_exercises
                WHERE workout_id = %s AND exercise_id = ANY(%s)
            """, (workout_id, list(to_delete)))

        # update or add exercises
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
                ex["exercise_id"]
            ))
            updated_exercise = cursor.fetchone()

            if not updated_exercise:
                cursor.execute("""
                    INSERT INTO workout_exercises (workout_id, exercise_id, sets, reps)
                    VALUES (%s, %s, %s, %s)
                """, (
                    workout_id,
                    ex["exercise_id"],
                    ex.get("sets"),
                    ex.get("reps")
                ))

        # fetching updated data workouts and exercises
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

      
        cursor.execute("""
            SELECT e.id, e.name, e.muscle_group, e.equipment, we.sets, we.reps
            FROM exercises e
            JOIN workout_exercises we ON e.id = we.exercise_id
            WHERE we.workout_id = %s
        """, (workout_id,))

        updated_workout["exercises"] = cursor.fetchall()

        updated_workout["comments"] = []

        connection.commit()
        connection.close()

        return jsonify(updated_workout), 200

    except Exception as error:
        return jsonify({"error": str(error)}), 500

@workouts_blueprint.route('/workouts/<workout_id>', methods=['DELETE'])
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


