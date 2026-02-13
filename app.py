from flask import Flask, jsonify
from flask_cors import CORS
from auth_middleware import token_required
from auth_blueprint import authentication_blueprint
from workouts_blueprint import workouts_blueprint
from comments_blueprint import comments_blueprint
from exercises_blueprint import exercises_blueprint

app = Flask(__name__)
CORS(app)
app.register_blueprint(authentication_blueprint)
app.register_blueprint(workouts_blueprint)
app.register_blueprint(comments_blueprint)
app.register_blueprint(exercises_blueprint)



if __name__ == '__main__':
    app.run()
