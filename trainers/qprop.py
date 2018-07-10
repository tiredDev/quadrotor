import environments.envs as envs 
import policies.qprop as qprop
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
        self.mem_len = params["mem_len"]
        self.seed = params["seed"]
        self.render = params["render"]
        self.log_interval = params["log_interval"]
        self.warmup = params["warmup"]
        self.batch_size = params["batch_size"]
        self.save = params["save"]

        hidden_dim = params["hidden_dim"]
        state_dim = env.observation_space
        action_dim = env.action_space
        action_bound = self.env.action_bound[1]
        cuda = params["cuda"]

        self.actor = qprop.Actor(state_dim, hidden_dim, action_dim)
        self.target_actor = qprop.Actor(state_dim, hidden_dim, action_dim)
        self.critic = qprop.Critic(state_dim+action_dim, hidden_dim, action_dim)
        self.target_critic = qprop.Critic(state_dim+action_dim, hidden_dim, action_dim)
        self.memory = qprop.ReplayMemory(1000000)
        self.agent = qprop.QPROP(self.actor, 
                                self.critic, 
                                self.memory, 
                                self.target_actor, 
                                self.target_critic, 
                                action_bound, 
                                GPU=cuda)

        self.noise = utils.OUNoise(action_dim)
        self.noise.set_seed(self.seed)
        self.memory = qprop.ReplayMemory(self.mem_len)

        if cuda:
            self.Tensor = torch.cuda.FloatTensor
        else:
            self.Tensor = torch.Tensor

    def train(self):
        interval_avg = []
        avg = 0
        for ep in range(self.iterations):
            running_reward = 0
            state = self.Tensor(self.env.reset())
            states = []
            actions = []
            rewards = []
            log_probs = []
            for t in range(self.env.H):
                if ep % self.log_interval == 0:
                    self.env.render()          
                action, log_prob = self.agent.select_action(state)
                next_state, reward, done, _ = self.env.step(action.data[0].cpu().numpy())
                running_reward += reward
                next_state = self.Tensor(next_state)
                reward = self.Tensor([reward])
                self.memory.push(state[0], action[0], next_state[0], reward)
                states.append(state)
                actions.append(action)
                rewards.append(reward)
                log_probs.append(log_prob)
                if ep >= self.warmup:
                    for i in range(3):               
                        transitions = self.memory.sample(self.batch_size)
                        batch = qprop.Transition(*zip(*transitions))
                        self.agent.online_update(batch)
                if done:
                    break
                state = next_state
            trajectory = {"states": states,
                        "actions": actions,
                        "rewards": rewards,
                        "log_probs": log_probs}
            self.agent.offline_update(trajectory)
            interval_avg.append(running_reward)
            avg = (avg*(ep-1)+running_reward)/ep   
            if ep % self.log_interval == 0:
                interval = float(sum(interval_avg))/float(len(interval_avg))
                print('Episode {}\t Interval average: {:.2f}\t Average reward: {:.2f}'.format(ep, interval, avg))
                interval_avg = []