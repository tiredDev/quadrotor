import simulation.quadrotor2 as quad
import simulation.animation as ani
import simulation.config as cfg
from math import sqrt, pi
import numpy as np
import matplotlib.pyplot as pl
import policies.ddpg_multi as ddpg
import argparse
from ounoise import OUNoise
import torch
import torch.nn.functional as F
from itertools import count

parser = argparse.ArgumentParser(description='PyTorch MBPS Node')
parser.add_argument('--gamma', type=float, default=0.99, metavar='G', help='discount factor (default: 0.99)')
parser.add_argument('--seed', type=int, default=543, metavar='N', help='random seed (default: 543)')
parser.add_argument('--render', action='store_true', help='render the environment')
parser.add_argument('--log-interval', type=int, default=10, metavar='N', help='interval between training status logs (default: 10)')
parser.add_argument('--warmup', type=int, default=100, metavar='w', help='number of warmup episodes')
parser.add_argument('--batch-size', type=int, default=64, metavar='bs', help='training batch size')
parser.add_argument('--load', default=False, type=bool, metavar='l', help='path to latest checkpoint (default: none)')
parser.add_argument('--save', type=bool, default=True, metavar='s', help='saves the model (default is True)')
parser.add_argument('--save-epochs', type=int, default=100, metavar='ep', help='save every n epochs (default 100)')
parser.add_argument('--load-path', type=str, default='', metavar='lp', help='load path string')
parser.add_argument('--cuda', type=bool, default=True, metavar='c', help='use CUDA for GPU acceleration (default True)')
parser.add_argument('--plot-interval', type=int, default=100, metavar='pi', help='interval between plot updates')
args = parser.parse_args()

if args.cuda:
    Tensor = torch.cuda.FloatTensor
else:
    Tensor = torch.Tensor

epochs = 250000
state_dim = 27
action_dim = 4
hidden_dim = 32

params = cfg.params
iris = quad.Quadrotor(params)
hover_rpm = iris.hov_rpm
trim = np.array([hover_rpm, hover_rpm, hover_rpm, hover_rpm])
action_bound = iris.max_rpm
sim_dt = iris.dt
ctrl_dt = 0.05
T = 2.5
steps = int(T/ctrl_dt)
dist_thresh = 1e-4
max_rad = 1.5
sim_steps = int(ctrl_dt/sim_dt)

actor = ddpg.Actor(state_dim, action_dim)
target_actor = ddpg.Actor(state_dim, action_dim)
critic = ddpg.Critic(state_dim, action_dim)
target_critic = ddpg.Critic(state_dim, action_dim)
agent = ddpg.DDPG(action_bound, actor,target_actor,critic,target_critic)

if args.cuda:
    agent = agent.cuda()

noise = OUNoise(action_dim)
noise.set_seed(args.seed)
memory = ddpg.ReplayMemory(1000000)

vis = ani.Visualization(iris, 10, quaternion=True)

def terminate(xyz, zeta, uvw, uvw_dot, rel_dist):
    #mask1 = zeta[:2] > pi/2
    #mask2 = zeta[:2] < -pi/2
    mask3 = np.abs(xyz) > 6
    if np.sum(mask3) > 0:
        return True
    if (rel_dist**2).sum() < dist_thresh:
        return True

last_xyz_dist = None
last_zeta_dist = None
last_uvw_dist = None
last_pqr_dist = None
def reward(rel_xyz, rel_zeta, rel_uvw, rel_pqr, action):
    
    global last_xyz_dist
    global last_zeta_dist
    global last_uvw_dist
    global last_pqr_dist
    
    err_xyz = (rel_xyz**2).mean()
    err_zeta = (rel_zeta**2).mean()
    err_uvw = (rel_uvw**2).mean()
    err_pqr = (rel_pqr**2).mean()
    
    xyz_loss = last_xyz_dist-err_xyz
    zeta_loss = last_zeta_dist-err_zeta
    uvw_loss = last_uvw_dist-err_uvw
    pqr_loss = last_pqr_dist-err_pqr
    
    last_xyz_dist = err_xyz
    last_zeta_dist = err_zeta
    last_uvw_dist = err_uvw
    last_pqr_dist = err_pqr
    
    action_rew = -(action**2).sum()/400000.
    
    bonus = 0.
    if err_xyz < dist_thresh:
        bonus = 1000.
    
    dist_rew = (-err_xyz).exp()+(-err_zeta).exp()+(-err_uvw).exp()+(-err_pqr).exp()
    ctrl_rew = xyz_loss+zeta_loss+uvw_loss/100.+pqr_loss/100.
    return dist_rew+ctrl_rew+action_rew+bonus+5.

def numpy_to_pytorch(xyz, zeta, uvw, pqr):
    xyz = torch.from_numpy(xyz.T).float()
    zeta = torch.from_numpy(zeta.T).float()
    uvw = torch.from_numpy(uvw.T).float()
    pqr = torch.from_numpy(pqr.T).float()
    if args.cuda:
        xyz = xyz.cuda()
        zeta = zeta.cuda()
        uvw = uvw.cuda()
        pqr = pqr.cuda()
    return xyz, zeta, uvw, pqr

def generate_goal(r):
    sph = Tensor(2).uniform_(-2*pi, 2*pi)
    x = r*sph[1].sin()*sph[0].cos()
    y = r*sph[1].sin()*sph[0].sin()
    z = r*sph[1].cos()
    xyz = Tensor([[x, y, z]])
    zeta = Tensor([[0.,0.,0.]])
    uvw = Tensor([[0.,0.,0.]])
    pqr = Tensor([[0.,0.,0.]])
    return xyz, zeta, uvw, pqr

def render(axis3d, goal, t):
    pl.figure(0)
    axis3d.cla()
    vis.draw3d_quat(axis3d)
    vis.draw_goal(axis3d, goal)
    axis3d.set_xlim(-3, 3)
    axis3d.set_ylim(-3, 3)
    axis3d.set_zlim(0, 6)
    axis3d.set_xlabel('West/East [m]')
    axis3d.set_ylabel('South/North [m]')
    axis3d.set_zlabel('Down/Up [m]')
    axis3d.set_title("Time %.3f s" %(t*ctrl_dt))
    pl.pause(0.001)
    pl.draw()

def main():
    pl.close("all")
    pl.ion()
    fig = pl.figure(0)
    axis3d = fig.add_subplot(111, projection='3d')

    interval_avg = []
    avg = 0
    frames = 2
    counter = 0
    global last_xyz_dist
    global last_zeta_dist
    global last_uvw_dist
    global last_pqr_dist
    for ep in count(1):

        # reset to [0,0,0], [0,0,0], [0,0,0], [0,0,0]
        xyz, zeta, _, uvw, pqr = iris.reset()
        xyz, zeta, uvw, pqr = numpy_to_pytorch(xyz, zeta, uvw, pqr)
        state = torch.cat([zeta.sin(), zeta.cos(), uvw, pqr],dim=1)

        # generate random goal state
        radius = Tensor(1).uniform_(0,max_rad)
        xyz_g, zeta_g, uvw_g, pqr_g = generate_goal(radius) 
        rel_dist = xyz_g-xyz
        rel_ang = zeta_g-zeta
        rel_uvw = uvw_g-uvw
        rel_pqr = pqr_g-pqr
        goal_init = torch.cat([rel_dist, rel_ang.sin(), rel_ang.cos(), rel_uvw, rel_pqr], dim=1)
        
        # reset noise, last distance to None, running reward to zero
        last_xyz_dist = (rel_dist**2).mean()
        last_zeta_dist = (rel_ang**2).mean()
        last_uvw_dist = (rel_uvw**2).mean()
        last_pqr_dist = (rel_pqr**2).mean()
        noise.reset()
        running_reward = 0
        for t in range(steps):
            
            # initialize goal to relative distance
            if t == 0:
                goal = goal_init
            
            # render the episode
            if ep % args.log_interval == 0:
                if counter%frames == 0:
                    render(axis3d, goal_init, t)
                    counter = 0
            
            # select an action using either random policy or trained policy
            if ep < args.warmup:
                action = agent.random_action(noise).data
            else:
                state_goal = torch.cat([state, goal], dim=1)
                action = agent.select_action(state_goal,noise=noise).data
            
            # step simulation forward
            for j in range(sim_steps):
                xyz, zeta, _, uvw, pqr = iris.step(action.cpu().numpy()[0])
            
            xyz_nn, zeta_nn, uvw_nn, pqr_nn = numpy_to_pytorch(xyz, zeta, uvw, pqr)
            next_state = torch.cat([zeta_nn.sin(), zeta_nn.cos(), uvw_nn, pqr_nn],dim=1)

            # get new relative distance
            rel_dist = xyz_g-xyz_nn
            rel_ang = zeta_g-zeta_nn
            rel_uvw = uvw_g-uvw_nn
            rel_pqr = pqr_g-pqr_nn
            goal = torch.cat([rel_dist, rel_ang.sin(), rel_ang.cos(), rel_uvw, rel_pqr], dim=1)
            
            # calc reward
            r = reward(rel_dist, rel_ang, rel_uvw, rel_pqr, action)
            running_reward += r
            
            # push to replay memory
            memory.push(state.squeeze(0), action.squeeze(0), next_state.squeeze(0), r.unsqueeze(0), goal.squeeze(0))
            
            # online training if out of warmup phase
            if ep >= args.warmup:
                for i in range(3):
                    transitions = memory.sample(args.batch_size)
                    batch = ddpg.Transition(*zip(*transitions))
                    agent.update(batch)
            
            # check if terminate
            if terminate(xyz, zeta, uvw, pqr, rel_dist):
                break
            state = next_state
            counter += 1

        interval_avg.append(running_reward)
        avg = (avg*(ep-1)+running_reward)/ep   
        if ep % args.log_interval == 0:
            interval = float(sum(interval_avg))/float(len(interval_avg))
            print('Episode {}\t Interval average: {:.2f}\t Average reward: {:.2f}'.format(ep, interval, avg))
            interval_avg = []
            
if __name__ == '__main__':
    main()