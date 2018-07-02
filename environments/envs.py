import environments.flying_skills as flying_skills
import environments.maneuvers as maneuvers
import environments.box_world as box_world
import environments.hover as hover
import environments.perching as perching
import environments.rapid_descent as rapid_descent
import environments.straight_and_level as straight_and_level
import environments.model_training as model_training

def make(name):
    if name == "flying_skills":
        return flying_skills.Environment()
    if name == "maneuvers":
        return maneuvers.Environment()
    if name == "box_world":
        return box_world.Environment()
    if name == "hover":
        return hover.Environment()
    if name == "perching":
        return perching.Environment()
    if name == "rapid_descent":
        return rapid_descent.Environment()
    if name == "straight_and_level":
        return straight_and_level.Environment()
    if name == "model_training":
        return model_training.Environment()