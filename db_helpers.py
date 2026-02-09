import os
import psycopg2


def get_db_connection():
    connection = psycopg2.connect(
        host='localhost',
        database=os.getenv('POSTGRES_DATABASE'),
        user=os.getenv('POSTGRES_USERNAME'),
        password=os.getenv('POSTGRES_PASSWORD')
    )
    return connection


def consolidate_comments_in_workouts(workouts_with_comments):
    print(workouts_with_comments)
    consolidated_workouts = []
    for workout in workouts_with_comments:
        # Check if this workout has already been added to consolidated_workouts
        workout_exists = False
        for consolidated_workout in consolidated_workouts:
            if workout["id"] == consolidated_workout["id"]:
                workout_exists = True
                consolidated_workout["comments"].append(
                    {"comment_text": workout["comment_text"],
                     "comment_id": workout["comment_id"],
                     "comment_author_username": workout["comment_author_username"]
                     })
                break

        # If the workout doesn't exist in consolidated_workouts, add it
        if not workout_exists:
            workout["comments"] = []
            if workout["comment_id"] is not None:
                workout["comments"].append(
                    {"comment_text": workout["comment_text"],
                     "comment_id": workout["comment_id"],
                     "comment_author_username": workout["comment_author_username"]
                     }
                )
            del workout["comment_id"]
            del workout["comment_text"]
            del workout["comment_author_username"]
            consolidated_workouts.append(workout)

    return consolidated_workouts
