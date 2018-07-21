import torch
import random
import torch.nn.functional as F
from torch.distributions import Normal
from collections import namedtuple

"""
    Pytorch implementation of Q-Prop (Gu et al., 2017). The paper implements the advantage estimation function
    though we can also use the Q-function directly; this implementation uses the Q-function form. 
    
    The goal of this method is to use the Q-function directly as a control variate to minimize variance in the 
    policy search. I've tested this code in the Mujoco Ant-v1 environment, where it makes steady progress even 
    without CUDA. In my experiments, the agent plateauxed at around 900-1000 points after a few hours of training.

    -- Sean Morrison, 2018
"""

class QPROP(torch.nn.Module):
    def __init__(self, actor, critic, memory, target_actor, target_critic, network_settings, GPU=False):
        super(QPROP,self).__init__()
        self.actor = actor
        self.critic = critic
        self.memory = memory
        self.target_actor = target_actor
        self.target_critic = target_critic

        self.crit_loss = torch.nn.L1Loss()

        self.crit_opt = torch.optim.Adam(self.critic.parameters())
        self.pol_opt = torch.optim.Adam(self.actor.parameters())

        self.gamma = network_settings["gamma"]
        self.tau = network_settings["tau"]

        self.hard_update(target_actor, actor)
        self.hard_update(target_critic, critic)

        self.GPU = GPU
        
        if GPU:
            self.Tensor = torch.cuda.FloatTensor
            self.actor = self.actor.cuda()
            self.target_actor = self.target_actor.cuda()
            self.critic = self.critic.cuda()
            self.target_critic = self.target_critic.cuda()
        else:
            self.Tensor = torch.Tensor

    def soft_update(self, target, source, tau):
	    for target_param, param in zip(target.parameters(), source.parameters()):
		    target_param.data.copy_(target_param.data*(1.0-tau)+param.data*tau)
    
    def hard_update(self, target, source):
        for target_param, param in zip(target.parameters(), source.parameters()):
            target_param.data.copy_(param.data)
    
    def select_action(self, x):
        mu, logvar = self.actor(x)
        std = logvar.exp().sqrt()+torch.ones(x.size()[0], self.actor.output_dim)*1e-4
        a = Normal(mu, std)
        action = a.sample()
        logprob = a.log_prob(action)
        return F.sigmoid(action).pow(0.5), logprob
    
    def online_update(self, batch):
        state = torch.stack(batch.state)
        action = torch.stack(batch.action)
        reward = torch.stack(batch.reward)
        next_state = torch.stack(batch.next_state)

        # update state-action value function off-policy
        with torch.no_grad():
            next_action_mu, _  = self.target_actor(next_state)
            q_next = self.target_critic(torch.cat([next_state, next_action_mu], dim=1))
        target = reward+self.gamma*q_next
        q = self.critic(torch.cat([state, action],dim=1))
        q_loss = self.crit_loss(q, target)
        self.crit_opt.zero_grad()
        q_loss.backward()
        self.crit_opt.step()

        # soft update of critic (polyak averaging)
        self.soft_update(self.target_critic, self.critic, self.tau)

    def offline_update(self, trajectory):
        state = trajectory["states"]
        action = trajectory["actions"]
        action_logprobs = trajectory["log_probs"]
        reward = trajectory["rewards"]
        rewards = []
        R = 0.
        for r in reward[::-1]:
            R = r.float()+self.gamma*R
            rewards.insert(0, R)
        q_act = torch.stack(rewards)
        state = torch.stack(state).squeeze(1)
        action = torch.stack(action).squeeze(1)
        action_logprobs = torch.stack(action_logprobs).squeeze(1)

        q_vals = self.critic(torch.cat([state, action],dim=1))
        q_hat = q_act-q_vals.detach()
        q_hat = (q_hat-q_hat.mean())/q_hat.std()
        self.pol_opt.zero_grad()
        loss = -(action_logprobs.sum(dim=1, keepdim=True)*(q_hat+q_vals)).sum()
        loss.backward()
        self.pol_opt.step()
        self.soft_update(self.target_actor, self.actor, self.tau)

class Actor(torch.nn.Module):
    def __init__(self, input_dim, hidden_dim, output_dim):
        super(Actor,self).__init__()
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.output_dim = output_dim

        self.l1 = torch.nn.Linear(input_dim, hidden_dim)
        self.mu = torch.nn.Linear(hidden_dim, output_dim)
        self.logvar = torch.nn.Linear(hidden_dim, output_dim)
    
    def forward(self, x):
        x = F.relu(self.l1(x))
        a_mu = self.mu(x)
        a_logvar = self.logvar(x)
        return a_mu, a_logvar

class Critic(torch.nn.Module):
    def __init__(self, input_dim, hidden_dim, output_dim):
        super(Critic,self).__init__()
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.output_dim = output_dim

        self.l1 = torch.nn.Linear(input_dim, hidden_dim)
        self.l2 = torch.nn.Linear(hidden_dim, output_dim)
    
    def forward(self, x):
        x = F.relu(self.l1(x))
        return self.l2(x)

Transition = namedtuple('Transition', ['state', 'action', 'next_state', 'reward'])
class ReplayMemory:
    def __init__(self, capacity):
        self.capacity = capacity
        self.memory = []
        self.position = 0

    def push(self, *args):
        if len(self.memory) < self.capacity:
            self.memory.append(None)
        self.memory[self.position] = Transition(*args)
        self.position = (self.position+1)%self.capacity

    def sample(self, batch_size):
        if self.__len__() < batch_size:
            return self.memory
        else:
            return random.sample(self.memory, batch_size)

    def __len__(self):
        return len(self.memory)
