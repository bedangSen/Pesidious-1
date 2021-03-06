import warnings
warnings.filterwarnings("ignore")

import logging
from logging import basicConfig, exception, debug, error, info, warning, getLogger
import argparse
import numpy as np
from itertools import count

from pathlib import Path
from tqdm import tqdm
from datetime import date
import os

from rich.logging import RichHandler
from rich.progress import Progress, TaskID, track
from rich.traceback import install
from rich import print
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from pyfiglet import Figlet

from collections import namedtuple, deque
from statistics import mean 

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.distributions import Categorical

import gym
import gym_malware
from gym_malware.envs.utils import interface, pefeatures
from gym_malware.envs.controls import manipulate2 as manipulate
ACTION_LOOKUP = {i: act for i, act in enumerate(
    manipulate.ACTION_TABLE.keys())}

def put_banner():
    # Printing heading banner
    f = Figlet(font="banner4")
    grid = Table.grid(expand=True, padding=1, pad_edge=True)
    grid.add_column(justify="right", ratio=38)
    grid.add_column(justify="left", ratio=62)
    grid.add_row(
        Text.assemble((f.renderText("PE"), "bold red")),
        Text(f.renderText("Sidious"), "bold white"),
    )
    print(grid)
    print(
        Panel(
            Text.assemble(
                ("Creating Chaos with Mutated Evasive Malware with ", "grey"),
                ("Reinforcement Learning ", "bold red"),
                ("and "),
                ("Generative Adversarial Networks", "bold red"),
                justify="center",
            )
        )
    )

put_banner()

def parse_args():
    parser = argparse.ArgumentParser(description='Reinforcement Training Module')

    parser.add_argument('--rl_gamma', type=float, default=0.99, metavar='G',
                        help='discount factor (default: 0.99)')
    parser.add_argument('--seed', type=int, default=543, metavar='N',
                        help='random seed (default: 543)')
    
    parser.add_argument('--rl_episodes', type=float, default=30000,
                        help='number of episodes to execute (default: 30000)')
    parser.add_argument('--rl_mutations', type=float, default=80,
                        help='number of maximum mutations allowed (default: 80)')
    
    parser.add_argument('--rl_save_model_interval', type=float, default=500,
                        help='Interval at which models should be saved (default: 500)') #gitul
    parser.add_argument('--rl_output_directory', type= Path, default=Path("rl_models"),
                        help='number of episodes to execute (default: rl_models/)') #gitul

    parser.add_argument("--logfile", help = "The file path to store the logs. (default : rl_features_logs_" + str(date.today()) + ".log)", type = Path, default = Path("rl_features_logs_" + str(date.today()) + ".log"))
    logging_level = ["debug", "info", "warning", "error", "critical"]
    parser.add_argument(
        "-l",
        "--log",
        dest="log",
        metavar="LOGGING_LEVEL",
        choices=logging_level,
        default="info",
        help=f"Select the logging level. Keep in mind increasing verbosity might affect performance. Available choices include : {logging_level}",
    )

    args = parser.parse_args()
    return args

def logging_setup(logfile: str , log_level: str):

    from imp import reload
    reload(logging)

    log_dir = "Logs"

    if not os.path.exists(log_dir):
        os.mkdir(log_dir)

    logfile = os.path.join(log_dir, logfile)

    basicConfig(
        level=log_level.upper(),
        filemode='a',  # other options are w for write.
        format="%(message)s",
        filename=logfile
    )

    getLogger().addHandler(RichHandler())
    
    info("[*] Starting Reinforcement Learning Agent's Training ...\n")

args = parse_args()
logging_setup(str(args.logfile), args.log)


class Policy(nn.Module):
    def __init__(self, env):
        super(Policy, self).__init__()
        self.layers = nn.Sequential(
            nn.Dropout(0.1),
            nn.Linear(env.observation_space.shape[0], 1024),
            nn.BatchNorm1d(1024),
            nn.ELU(alpha=1.0),
            nn.Linear(1024, 256),
            nn.BatchNorm1d(256),
            nn.ELU(alpha=1.0),
            nn.Linear(256, env.action_space.n)
        )

        self.saved_log_probs = []
        self.rewards = []

    def forward(self, x):
        action_scores =  self.layers(x)
        return action_scores

def update_epsilon(n):
    epsilon_start = 1.0
    epsilon = epsilon_start
    epsilon_final = 0.4
    epsilon_decay = 1000 # N from the research paper (equation #6)

    epsilon = 1.0 - (n/epsilon_decay)

    if epsilon <= epsilon_final:
        epsilon = epsilon_final

    return epsilon

def select_action(observation, epsilon, env, policy):

    rand = np.random.random()
    if rand < epsilon:
        action = np.random.choice(env.action_space.n)
        return action

    actions = policy.forward(observation)
    m = Categorical(actions)
    action = m.sample()
    policy.saved_log_probs.append(m.log_prob(action))
    debug(f"PRinting ACtion [bold green] {action}", extra={"markup":True})
    return action.item()

class RangeNormalize(object):
    def __init__(self, 
                 min_val, 
                 max_val):
        """
        Normalize a tensor between a min and max value
        Arguments
        ---------
        min_val : float
            lower bound of normalized tensor
        max_val : float
            upper bound of normalized tensor
        """
        self.min_val = min_val
        self.max_val = max_val

    def __call__(self, *inputs):
        outputs = []
        for idx, _input in enumerate(inputs):
            _min_val = _input.min()
            _max_val = _input.max()
            a = (self.max_val - self.min_val) / (_max_val - _min_val)
            b = self.max_val- a * _max_val
            _input = (_input * a ) + b
            outputs.append(_input)
        return outputs if idx > 1 else outputs[0]

def finish_episode(gamma, policy):

    R = 0
    policy_loss = []
    returns = []
    for r in policy.rewards[::-1]:
        R = r + gamma * R
        returns.insert(0, R)
    returns = torch.tensor(returns)
    returns = (returns - returns.mean()) / (returns.std() + eps)
    for log_prob, R in zip(policy.saved_log_probs, returns):
        policy_loss.append(-log_prob * R)
    optimizer.zero_grad()
    policy_loss = torch.cat(policy_loss).sum()
    policy_loss.backward()
    optimizer.step()
    del policy.rewards[:]
    del policy.saved_log_probs[:]


device = torch.device("cpu")

info("[*] Initilializing environment ...\n")
env = gym.make("malware-score-v0")
env.seed(args.seed)
torch.manual_seed(args.seed)

info("[*] Initilializing Neural Network model ...")
policy = Policy(env)
optimizer = optim.Adam(policy.parameters(), lr=1e-2)
eps = np.finfo(np.float32).eps.item()

def main():
    
    info("[*] Starting training ...")
    running_reward = 10

    rn = RangeNormalize(-0.5,0.5)
    D = args.rl_episodes # as mentioned in the research paper (total number of episodes)
    T = args.rl_mutations # as mentioned in the paper (total number of mutations that the agent can perform on one file)
    n = 0
    
    for i_episode in range(1, D):
        try: 
            state, ep_reward = env.reset(), 0
            state_norm = rn(state)
            state_norm = torch.from_numpy(state_norm).float().unsqueeze(0).to(device)
            epsilon = update_epsilon(i_episode)
            for t in range(1, T):  # Don't infinite loop while learning
                action = select_action(state_norm, epsilon, env, policy)
                state, reward, done, _ = env.step(action)
                policy.rewards.append(reward)
                ep_reward += reward
                debug("\t[+] Episode : " + str(i_episode) + " , Mutation # : " + str(t) + " , Mutation : " + str(ACTION_LOOKUP[action]) + " , Reward : " + str(reward))
                if done:
                    break

            debug('\t[+] Episode Over')
            finish_episode(args.rl_gamma, policy)
            print("here epside " + str(i_episode) + " arg " + str(args.rl_save_model_interval))
            if i_episode % args.rl_save_model_interval == 0:
                if not os.path.exists(args.rl_output_directory):
                    os.mkdir(args.rl_output_directory)
                    info("[*] Feature vector directory has been created at : " + args.rl_output_directory)
                torch.save(policy.state_dict(), os.path.join(args.rl_output_directory, "rl-model-" + str(i_episode) + "-" +str(date.today()) + ".pt" ))
                info("[*] Saving model in rl-model/ directory ...")
        
        except Exception as e:
            #print("exception " + e)
            continue

if __name__ == '__main__':
    main()
