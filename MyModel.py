import torch
import torch.nn as nn
import torch.nn.functional as F


class MyModel(nn.Module):
    def __init__(self):
        super(MyModel).__init__()
        self.reset_parameters()

    def forward(self):
        """
        :input:  (DataLoader)
        :return: (batch, probablilties)
        """
        return

    def reset_parameters(self):
        pass

    def __repr__(self):
        return self.__class__.__name__