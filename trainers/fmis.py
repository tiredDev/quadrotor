import environments.envs as envs 
import policies.fmis as fmis
import argparse
import torch
import torch.nn.functional as F
import utils

class Trainer:
    def __init__(self, env, params):
        self.env = envs.make(env)
        self.params = params

        self.iterations = params["iterations"]
        self.gamma = params["gamma"]
        self.seed = params["seed"]
        self.render = params["render"]
        self.log_interval = params["log_interval"]
        self.save = params["save"]
        
        cuda = params["cuda"]
        action_bound = self.env.action_bound[1]
        state_dim = self.env.observation_space
        action_dim = self.env.action_space
        hidden_dim = params["hidden_dim"]

        self.pi = fmis.Actor(state_dim, hidden_dim, action_dim)
        self.beta = fmis.Actor(state_dim, hidden_dim, action_dim)
        self.phi = fmis.Dynamics(state_dim+action_dim, hidden_dim, state_dim)
        self.critic = fmis.Critic(state_dim, hidden_dim, 1)
        self.agent = fmis.FMIS(self.pi, self.beta, self.critic, self.phi, action_bound, GPU=cuda)

        self.pi_optim = torch.optim.Adam(self.pi.parameters())
        self.phi_optim = torch.optim.Adam(self.phi.parameters())

        if cuda:
            self.Tensor = torch.cuda.FloatTensor
        else:
            self.Tensor = torch.Tensor

    def train(self):
        interval_avg = []
        avg = 0
        for ep in range(self.iterations):
            running_reward = 0
            s_ = []
            a_ = []
            ns_ = []
            state = self.Tensor(self.env.reset())
            s0 = state.clone()
            for _ in range(self.env.H):
                if ep % self.log_interval == 0:
                    self.env.render()          
                action, _ = self.agent.select_action(state)
                next_state, reward, done, _ = self.env.step(action[0].cpu().numpy())
                running_reward += reward
                next_state = self.Tensor(next_state)
                s_.append(state[0])
                a_.append(action[0])
                ns_.append(next_state[0])
                if done:
                    break
                state = next_state
            trajectory = {"states": s_,
                        "actions": a_,
                        "next_states": ns_}
            for i in range(1):
                self.agent.model_update(self.pi_optim, trajectory)
            for i in range(1):
                self.agent.policy_update(self.phi_optim, s0, self.env.H)
            interval_avg.append(running_reward)
            avg = (avg*(ep-1)+running_reward)/ep   
            if ep % self.log_interval == 0:
                interval = float(sum(interval_avg))/float(len(interval_avg))
                print('Episode {}\t Interval average: {:.2f}\t Average reward: {:.2f}'.format(ep, interval, avg))
                interval_avg = []