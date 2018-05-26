import math
import torch
import matplotlib.pyplot as plt
import matplotlib.style as style
import pandas as pd
import random
import numpy as np

"""
    This module contains utility functions and classes that would clutter up other scripts. These include getting
    trajectory information from the dataset, doing Euler angle quaternion conversions, saving and loading models,
    and logging functionality. If you need some kind of visualization of utility function to be implemented and it
    doesn't make sense for it to go anywhere else, this is where it belongs.
"""

style.use('seaborn-white')
#plt.rc('xtick',labelsize=8)
#plt.rc('ytick',labelsize=8)
#plt.rc('axes',titlesize=10, labelsize=10, facecolor='white')
#plt.rc('legend',fontsize=10)
#plt.rc('figure',facecolor='white')

def get_trajectories(df, state_dim, action_dim, batchsize, H, dt):
    seq_len = int(H/dt)
    states = np.zeros((seq_len, batchsize, state_dim+1))
    actions = np.zeros((seq_len, batchsize, action_dim))
    next_states = np.zeros((seq_len, batchsize, state_dim))
    data = df.loc[df['len'] == seq_len]
    for i in range(batchsize):
        initial = data.sample(n=1)
        key = initial[['key']].values
        sequence = df.loc[df['key'] == key[0][0]]
        states[:,i,:] = sequence[['X0','Y0','Z0','ROLL0','PITCH0','YAW0','U0','V0','W0','Q01','Q02','Q03','O01','O02','O03','O04','dt']].values
        actions[:,i,:] = sequence[['A01','A02','A03','A04']].values
        next_states[:,i,:] = sequence[['X1','Y1','Z1','ROLL1','PITCH1','YAW1','U1','V1','W1','Q11','Q12','Q13','O11','O12','O13','O14']].values
    return states, actions, next_states

def euler_angle_to_quaternion(roll, pitch, yaw):
    cr = math.cos(roll*0.5)
    sr = math.sin(roll*0.5)
    cp = math.cos(pitch*0.5)
    sp = math.sin(pitch*0.5)
    cy = math.cos(yaw*0.5)
    sy = math.sin(yaw*0.5)
    q_w = cy*cr*cp+sy*sr*sp
    q_x = cy*sr*cp-sy*cr*sp
    q_y = cy*cr*sp+sy*sr*cp
    q_z = sy*cr*cp-cy*sr*sp
    return [q_x, q_y, q_z, q_w]

def quaternion_to_euler_angle(x, y, z, w):
	ysqr = y*y
	t0 = +2.0*(w*x+y*z)
	t1 = +1.0-2.0*(x*x+ysqr)
	roll = math.atan2(t0,t1)
	t2 = +2.0*(w*y-z*x)
	t2 = +1.0 if t2 > +1.0 else t2
	t2 = -1.0 if t2 < -1.0 else t2
	pitch = math.asin(t2)
	t3 = +2.0*(w*z+x*y)
	t4 = +1.0-2.0*(ysqr+z*z)
	yaw = math.atan2(t3,t4)
	return roll, pitch, yaw

def average_gradient(model):
    mean = []
    for param in model.parameters():
        mean.append(param.grad.mean().item())
    return float(sum(mean))/float(len(mean))

def print_gradients(model):
    for param in model.parameters():
        print(param.grad)

def save(state, filename='checkpoint.pth.tar'):
    print("=> saving model in '{}'".format(filename))
    torch.save(state, filename)

def resume(model):
    print("=> loading model '{}'".format(model))
    return torch.load(model)

def progress(count, total, loss):
    bar_len = 50
    filled_len = int(round(bar_len * count / float(total)))
    percent = round(100.0 * count / float(total), 1)
    loss = tuple([round(x, 5) if isinstance(x, float) else x for x in loss])
    bar = '#' * filled_len + '-' * (bar_len - filled_len)
    print('[{}] {}%, Loss: {}'.format(bar, percent, loss), end='\r', flush=True)

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

class Logger():
    def __init__(self, title, xlab, ylab):
        self.fig1 = plt.figure()
        self.ax1 = self.fig1.add_subplot(111)
        self.ax1.set_title(title)
        self.ax1.set_xlabel(xlab)
        self.ax1.set_ylabel(ylab)
        self.fig1.subplots_adjust(hspace=0.3)
        self.fig1.subplots_adjust(wspace=0.3)
        #self.fig1.tight_layout()
        self.fig1.show()

        self.legend = None

        self.ax1_data = [[],[]]
        self.ax1_val = [[],[]]

        self.model_counter = 0
        self.title = title
        self.xlab = xlab
        self.ylab = ylab

    def plot_graphs(self):
        self.ax1.clear()
        if not self.legend == None:
            self.legend.remove()
        p5, p6 = self.ax1.plot(self.ax1_data[:][0],self.ax1_data[:][1],self.ax1_val[:][0],self.ax1_val[:][1])

        self.ax1.set_title(self.title)
        self.ax1.set_xlabel(self.xlab)
        self.ax1.set_ylabel(self.ylab)
        
        self.legend = self.fig1.legend((p5, p6), ('Train', 'Validation'))

        self.fig1.canvas.draw()

    def update_data(self, J, J_val):
        i = self.model_counter
        self.ax1_data[0].append(i)
        self.ax1_data[1].append(J)
        self.ax1_val[0].append(i)
        self.ax1_val[1].append(J_val)
        self.model_counter += 1

    def save_figure(self, name):
        self.fig1.savefig(name + '.pdf', bbox_inches='tight')

def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)

def cuda_if(torch_object, cuda):
    return torch_object.cuda() if cuda else torch_object

def gae(rewards, masks, values, gamma, lambd):
    """ Generalized Advantage Estimation
    Args:
        rewards (FloatTensor): rewards shaped [T x N x 1]
        masks (FloatTensor): continuation masks shaped [T x N x 1]
            zero at done timesteps, one otherwise
        values (Variable): value predictions shaped [(T + 1) x N x 1]
        gamma (float): discount factor
        lambd (float): GAE lambda parameter
    Returns:
        advantages (FloatTensor): advantages shaped [T x N x 1]
        returns (FloatTensor): returns shaped [T x N x 1]
    """
    T, N, _ = rewards.size()

    cuda = rewards.is_cuda

    advantages = torch.zeros(T, N, 1)
    advantages = cuda_if(advantages, cuda)
    advantage_t = torch.zeros(N, 1)
    advantage_t = cuda_if(advantage_t, cuda)

    for t in reversed(range(T)):
        delta = rewards[t] + values[t + 1].data * gamma * masks[t] - values[t].data
        advantage_t = delta + advantage_t * gamma * lambd * masks[t]
        advantages[t] = advantage_t

    returns = values[:T].data + advantages

    return advantages, returns


def mean_std_groups(x, y, group_size):
    num_groups = int(len(x) / group_size)

    x, x_tail = x[:group_size * num_groups], x[group_size * num_groups:]
    x = x.reshape((num_groups, group_size))

    y, y_tail = y[:group_size * num_groups], y[group_size * num_groups:]
    y = y.reshape((num_groups, group_size))

    x_means = x.mean(axis=1)
    x_stds = x.std(axis=1)

    if len(x_tail) > 0:
        x_means = np.concatenate([x_means, x_tail.mean(axis=0, keepdims=True)])
        x_stds = np.concatenate([x_stds, x_tail.std(axis=0, keepdims=True)])

    y_means = y.mean(axis=1)
    y_stds = y.std(axis=1)

    if len(y_tail) > 0:
        y_means = np.concatenate([y_means, y_tail.mean(axis=0, keepdims=True)])
        y_stds = np.concatenate([y_stds, y_tail.std(axis=0, keepdims=True)])

    return x_means, x_stds, y_means, y_stds

def set_lr(optimizer, lr):
    for param_group in optimizer.param_groups:
param_group['lr'] = lr
    
