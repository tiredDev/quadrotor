import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.autograd import Variable
import numpy as np

class Transition(nn.Module):
    def __init__(self, state_dim, action_dim, hidden_dim, GPU=True):
        super(Transition, self).__init__()
        self.lin_accel = MLP(state_dim+action_dim, hidden_dim, 3, GPU)
        self.ang_accel = MLP(state_dim+action_dim, hidden_dim, 3, GPU)
    
        self.lin_accel_opt = torch.optim.Adam(self.lin_accel.parameters(),lr=1e-4)
        self.ang_accel_opt = torch.optim.Adam(self.ang_accel.parameters(),lr=1e-4)
        self.GPU = GPU

        if GPU:
            self.Tensor = torch.cuda.FloatTensor
            self.lin_accel = self.lin_accel.cuda()
            self.ang_accel = self.ang_accel.cuda()
        else:
            self.Tensor = torch.Tensor
        
        self.zeta_norm = 0
        self.uvw_norm = 0
        self.pqr_norm = 0
        self.action_norm = 0
        self.uvw_dot_norm = 0
        self.pqr_dot_norm = 0

    def R1(self, zeta, v):
        phi = zeta[0,0]
        theta = zeta[0,1]
        psi = zeta[0,2]

        R_z = self.Tensor([[psi.cos(), -psi.sin(), 0],
                            [psi.sin(), psi.cos(), 0],
                            [0., 0., 1.]])
        R_y = self.Tensor([[theta.cos(), 0., theta.sin()],
                            [0., 1., 0.],
                            [-theta.sin(), 0, theta.cos()]])
        R_x =  self.Tensor([[1., 0., 0.],
                            [0., phi.cos(), -phi.sin()],
                            [0., phi.sin(), phi.cos()]])
        R = torch.matmul(R_z, torch.matmul(R_y, R_x))
        return torch.matmul(R, torch.t(v)).view(1,-1)

    def R2(self, zeta, w):
        theta = zeta[0,1]
        psi = zeta[0,2]

        x11 = psi.cos()/theta.cos()
        x12 = psi.sin()/theta.cos()
        x13 = 0
        x21 = -psi.sin()
        x22 = psi.cos()
        x23 = 0
        x31 = psi.cos()*theta.tan()
        x32 = psi.sin()*theta.tan()
        x33 = 1
        R = self.Tensor([[x11, x12, x13],
                        [x21, x22, x23],
                        [x31, x32, x33]])
        return torch.matmul(R, torch.t(w)).view(1,-1)

    def transition(self, x0, state_action, dt):
        # state_action is [sin(zeta), cos(zeta), v, w, a]
        xyz = x0.clone()
        uvw_pqr = state_action[:,6:12].clone()
        zeta = state_action[:,0:3].asin()
        uvw = uvw_pqr[:,0:3]
        pqr = uvw_pqr[:,3:]
        uvw_dot = self.lin_accel(state_action)*self.uvw_dot_norm
        pqr_dot = self.ang_accel(state_action)*self.pqr_dot_norm
        dv, dw = uvw_dot*dt, pqr_dot*dt
        uvw = uvw+dv
        pqr = pqr+dw
        xyz_dot = self.R1(zeta, uvw)
        zeta_dot = self.R2(zeta, pqr)
        dx, dzeta = xyz_dot*dt, zeta_dot*dt
        xyz = xyz+dx
        zeta = zeta+dzeta
        return xyz, zeta, uvw, pqr

    def update(self, zeta, uvw, pqr, action, uvw_dot, pqr_dot):
        zeta = zeta.reshape((1,-1))
        uvw = uvw.reshape((1,-1))
        pqr = pqr.reshape((1,-1))
        action = action.reshape((1,-1))
        uvw_dot = uvw_dot.reshape((1,-1))
        pqr_dot = pqr_dot.reshape((1,-1))

        zeta_norm = np.linalg.norm(zeta)
        uvw_norm = np.linalg.norm(uvw)
        pqr_norm = np.linalg.norm(pqr)
        action_norm = np.linalg.norm(action)
        uvw_dot_norm = np.linalg.norm(uvw_dot)
        pqr_dot_norm = np.linalg.norm(pqr_dot)

        if zeta_norm>self.zeta_norm:
            self.zeta_norm = zeta_norm
        if uvw_norm>self.uvw_norm:
            self.uvw_norm = uvw_norm
        if pqr_norm>self.pqr_norm:
            self.pqr_norm = pqr_norm
        if action_norm>self.action_norm:
            self.action_norm = action_norm
        if uvw_dot_norm>self.uvw_dot_norm:
            self.uvw_dot_norm = uvw_dot_norm
        if pqr_dot_norm>self.pqr_dot_norm:
            self.pqr_dot_norm = pqr_dot_norm
       
        zeta = torch.from_numpy(zeta).float()/self.zeta_norm
        uvw = torch.from_numpy(uvw).float()/self.uvw_norm
        pqr = torch.from_numpy(pqr).float()/self.pqr_norm
        action = torch.from_numpy(action).float()/self.action_norm
        uvw_dot = torch.from_numpy(uvw_dot).float()/self.uvw_dot_norm
        pqr_dot = torch.from_numpy(pqr_dot).float()/self.pqr_dot_norm

        if self.GPU:
            zeta = zeta.cuda()
            uvw = uvw.cuda()
            pqr = pqr.cuda()
            action = action.cuda()
            uvw_dot = uvw_dot.cuda()
            pqr_dot = pqr_dot.cuda()
        
        state = torch.cat([zeta.sin(), zeta.cos(), uvw, pqr],dim=1)
        state_action = torch.cat([state, action],dim=1)
        
        v_dot = self.lin_accel(state_action)
        w_dot = self.ang_accel(state_action)

        v_dot_loss = F.mse_loss(v_dot, uvw_dot)
        w_dot_loss = F.mse_loss(w_dot, pqr_dot)

        self.lin_accel_opt.zero_grad()
        self.ang_accel_opt.zero_grad()

        v_dot_loss.backward()
        w_dot_loss.backward()

        self.lin_accel_opt.step()
        self.ang_accel_opt.step()

        return v_dot_loss.item(), w_dot_loss.item()

class MLP(nn.Module):
    def __init__(self, input_dim, hidden_dim, output_dim, GPU):
        super(MLP, self).__init__()
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.output_dim = output_dim
        self.GPU = GPU
        
        self.affine1 = nn.Linear(input_dim, hidden_dim)
        torch.nn.init.xavier_uniform_(self.affine1.weight)

        self.output_head = nn.Linear(hidden_dim, output_dim)
        torch.nn.init.xavier_uniform_(self.output_head.weight)

        if GPU:
            self.Tensor = torch.cuda.FloatTensor
        else:
            self.Tensor = torch.Tensor

    def forward(self, x):
        x = F.relu(self.affine1(x))
        x = self.output_head(x)
        return x