from flask import Blueprint, jsonify, request, g
from db_helpers import get_db_connection
import psycopg2.extras
from auth_middleware import token_required

exercises_blueprint = Blueprint('exercises_blueprint', __name__)


@exercises_blueprint.route('/exercises', methods=['GET'])
@token_required
def get_exercises():
    try:
        connection = get_db_connection()
        cursor = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute("""
            SELECT id, name, muscle_group, equipment
            FROM exercises
            ORDER BY name;
        """)

        exercises = cursor.fetchall()
        connection.close()

        return jsonify(exercises), 200

    except Exception as error:
        return jsonify({"error": str(error)}), 500
    
    

@exercises_blueprint.route('/exercises', methods=['POST'])
@token_required
def create_exercise():
    try:
        new_exercise = request.get_json()

        connection = get_db_connection()
        cursor = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute("""
            INSERT INTO exercises (name, muscle_group, equipment)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (
            new_exercise['name'],
            new_exercise['muscle_group'],
            new_exercise['equipment']
        ))

        exercise_id = cursor.fetchone()["id"]

        cursor.execute("""
            SELECT id, name, muscle_group, equipment
            FROM exercises
            WHERE id = %s
        """, (exercise_id,))

        created_exercise = cursor.fetchone()
        connection.commit()
        connection.close()

        return jsonify(created_exercise), 201

    except Exception as error:
        return jsonify({"error": str(error)}), 500


@exercises_blueprint.route('/exercises/<exercise_id>', methods=['PUT'])
@token_required
def update_exercise(exercise_id):
    try:
        updated_data = request.get_json()

        connection = get_db_connection()
        cursor = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute("SELECT * FROM exercises WHERE id = %s", (exercise_id,))
        exercise = cursor.fetchone()

        if not exercise:
            connection.close()
            return jsonify({"error": "Exercise not found"}), 404

        cursor.execute("""
            UPDATE exercises
            SET name = %s, muscle_group = %s, equipment = %s
            WHERE id = %s
            RETURNING *
        """, (
            updated_data['name'],
            updated_data['muscle_group'],
            updated_data['equipment'],
            exercise_id
        ))

        updated_exercise = cursor.fetchone()
        connection.commit()
        connection.close()

        return jsonify(updated_exercise), 200

    except Exception as error:
        return jsonify({"error": str(error)}), 500


@exercises_blueprint.route('/exercises/<exercise_id>', methods=['DELETE'])
@token_required
def delete_exercise(exercise_id):
    try:
        connection = get_db_connection()
        cursor = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute("SELECT * FROM exercises WHERE id = %s", (exercise_id,))
        exercise = cursor.fetchone()

        if not exercise:
            connection.close()
            return jsonify({"error": "Exercise not found"}), 404

        cursor.execute("DELETE FROM exercises WHERE id = %s", (exercise_id,))
        connection.commit()
        connection.close()

        return jsonify({"message": "Exercise deleted successfully"}), 200

    except Exception as error:
        return jsonify({"error": str(error)}), 500
