# /usr/bin/env python3
# coding=utf-8
import torch

import torch.nn as nn
import torch.optim as optim

import torch.nn.functional as F
from torch.autograd import Variable
from torch.nn.parameter import Parameter

import torch.cuda
import numpy as np
import numpy.random as npr

from qpth.qp import QPFunction

import matplotlib.pyplot as plt

class LSTMModel(nn.Module):
    '''
    nn.LSTM Parameters:
        input_size  – The number of expected features in the input x
        hidden_size – The number of features in the hidden state h
        num_layers  – Number of recurrent layers.

    Inputs: input, (h_0, c_0)
        input (seq_len, batch, input_size)
        h_0 (num_layers * num_directions, batch, hidden_size)
        c_0 (num_layers * num_directions, batch, hidden_size)

    Outputs: output, (h_n, c_n)
        output (seq_len, batch, hidden_size * num_directions)
        h_n (num_layers * num_directions, batch, hidden_size)
        c_n (num_layers * num_directions, batch, hidden_size):

    QP Layer:
        nz = 6, neq = 0, nineq = 12, QPenalty = 0.1
    '''
    def __init__(self, nz, neq, nineq, Qpenalty, inputSize, nHidden, 
                 batchSize, noutputs=3, numLayers=2):

        super(LSTMModel, self).__init__()
        '''
        inputSize = 9, nHidden = [9,6,6], batchSize = 1
        '''

        # QP Parameters
        nx = nz     #cause inequality is double sided (see my notes)
        self.neq = neq
        self.nineq = nineq
        self.nz = nz
        self.nHidden = nHidden

        self.Q = Variable(Qpenalty*torch.eye(nx).cuda())
        self.p = Variable(torch.zeros(nx).cuda())
        G = torch.eye(nineq, nx)
        for i in range(nz):
            G[i][i] *= -1
        self.G = Variable(G.cuda())
        self.h = Variable(torch.ones(nineq).cuda())
        e = Variable(torch.Tensor().cuda())

        def qp_layer(x):
            '''
            Parameters:
              Q:  A (nBatch, nz, nz) or (nz, nz) Tensor.
              p:  A (nBatch, nz) or (nz) Tensor.
              G:  A (nBatch, nineq, nz) or (nineq, nz) Tensor.
              h:  A (nBatch, nineq) or (nineq) Tensor.
              A:  A (nBatch, neq, nz) or (neq, nz) Tensor.
              b:  A (nBatch, neq) or (neq) Tensor.

            Returns: \hat z: a (nBatch, nz) Tensor.
            '''
            nBatch = x.size(0)
            Q = self.Q  
            p = x.view(nBatch, -1) 
            G = self.G  
            h = self.h  
            e = Variable(torch.Tensor().cuda())
            x = QPFunction()(Q, p, G, h, e, e).cuda()
            return x
        self.qp_layer = qp_layer

        # Backprop Through Time (Recurrent Layer) Params
        self.cost = nn.MSELoss(size_average=False)
        self.noutputs = noutputs
        self.num_layers = numLayers
        self.inputSize = inputSize
        self.nHidden = nHidden
        self.batchSize = batchSize
        self.noutputs = noutputs
        self.criterion = nn.MSELoss(size_average=False)
        
        #define recurrent and linear layers
        self.lstm1  = nn.LSTM(inputSize,nHidden[0],num_layers=numLayers)
        self.lstm2  = nn.LSTM(nHidden[0],nHidden[1],num_layers=numLayers)
        self.lstm3  = nn.LSTM(nHidden[1],nHidden[2],num_layers=numLayers)
        self.fc     = nn.Linear(nHidden[2], noutputs)
        self.drop   = nn.Dropout(0.3)

    def forward(self, x):
        nBatch = x.size(0)

        # Set initial states 
        h0 = Variable(torch.Tensor(self.num_layers, self.batchSize, self.nHidden[0]).cuda()) 
        c0 = Variable(torch.Tensor(self.num_layers, self.batchSize, self.nHidden[0]).cuda())        
        # Forward propagate RNN layer 1
        out, _ = self.lstm1(x, (h0, c0)) 
        out = self.drop(out)
        
        # Set hidden layer 2 states 
        h1 = Variable(torch.Tensor(self.num_layers, self.batchSize, self.nHidden[1]).cuda()) 
        c1 = Variable(torch.Tensor(self.num_layers, self.batchSize, self.nHidden[1]).cuda())        
        # Forward propagate RNN layer 2
        out, _ = self.lstm2(out, (h1, c1))  
        
        # Set hidden layer 3 states 
        h2 = Variable(torch.Tensor(self.num_layers, self.batchSize, self.nHidden[2]).cuda()) 
        c2 = Variable(torch.Tensor(self.num_layers, self.batchSize, self.nHidden[2]).cuda())        
        # Forward propagate RNN layer 2
        out, _ = self.lstm3(out, (h2, c2)) 
        out = self.drop(out) 
        
        # Decode hidden state of last time step
        out = self.fc(out[:, -1, :]) 

        #Now add QP Layer
        out = out.view(nBatch, -1) 

        out = self.qp_layer(out)


        return out
        # '''