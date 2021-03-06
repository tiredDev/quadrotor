import math
from math import pi
import numpy as np
import torch
import torch.optim as optim
import torch.nn.functional as F
import utils
import numpy as np
import environments.envs as envs
import models.one_step as model
import os

GPU = False

def main():
    env = envs.make("model_training")
    max_rpm = env.action_bound[1]
    action_dim = env.action_space
    state_dim = env.observation_space
    epochs = 250000
    hidden_dim = 64
    dyn = model.Transition(state_dim, action_dim, hidden_dim, GPU)
    if GPU:
        dyn = dyn.cuda()
        Tensor = torch.cuda.FloatTensor
    else:
        Tensor = torch.Tensor

    counter = 0
    running = True
    H = 100
    noise = utils.OUNoise(action_dim, mu=10)
    env.init_rendering()
    while running:
        # set random state
        state = Tensor(env.reset())      
        state_actions = []
        next_states = []
        
        # run trajectory
        loss = 0
        for i in range(1, H+1):
            action = np.array([noise.noise()], dtype="float32")*env.action_bound[1]
            action_tensor = torch.from_numpy(action)
            if GPU:
                action_tensor = action_tensor.cuda()
            state_action = torch.cat([state, action_tensor],dim=1)
            next_state, _, _, _ = env.step(action.reshape(action_dim,))
            #env.render()
            next_state = Tensor(next_state)
            state_actions.append(state_action)
            next_states.append(next_state)
            state = next_state
        state_actions = torch.stack(state_actions).squeeze(1)
        next_states = torch.stack(next_states).squeeze(1)
        #print(state_actions.size())
        #print(next_states.size())
        traj = {"state_actions": state_actions,
                "next_states": next_states}
        loss = dyn.batch_update(traj)
        print("---Model loss: {:.8f}---".format(loss))

        counter += 1

        if counter > epochs:
            running = False
            print("Saving figures")
            directory = os.getcwd()
            """
            fig1.savefig(directory+"/figures/one_step_loss.pdf", bbox_inches="tight")
            """
            print("Saving model")
            torch.save(dyn, directory+"/saved_models/one_step.pth.tar")

if __name__ == "__main__":
    main()