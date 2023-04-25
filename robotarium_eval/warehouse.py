from gym import spaces
import numpy as np
import copy
from base import BaseEnv
from misc import *
from warehouse_visualize import Visualize
from roboEnv import roboEnv


class Agent:
    #These agents are specifically implimented for the warehouse scenario
    def __init__(self, index, action_id_to_word, action_word_to_id, goal='Red'):
        self.index = index
        self.goal = goal
        self.loaded = False
        self.action_id2w = action_id_to_word
        self.action_w2id = action_word_to_id

    
    def generate_goal(self, goal_pose, action, args):    
        '''
        updates the goal_pose based on the agent's actions
        '''   
        if self.action_id2w[action] == 'left':
                goal_pose[0] = max( goal_pose[0] - args.MIN_DIST, args.LEFT)
        elif self.action_id2w[action] == 'right':
                goal_pose[0] = min( goal_pose[0] + args.MIN_DIST, args.RIGHT)
        elif self.action_id2w[action] == 'up':
                goal_pose[1] = max( goal_pose[1] - args.MIN_DIST, args.UP)
        elif self.action_id2w[action] == 'down':
                goal_pose[1] = min( goal_pose[1] + args.MIN_DIST, args.DOWN)
        
        return goal_pose

class Warehouse(BaseEnv):
    def __init__(self, args):
        self.args = args
        self.num_robots = self.args.num_robots
        self.agent_poses = None

        #Agent agent's observation is [pos_x,pos_y,loaded] where loaded is a bool
        self.agent_obs_dim = 3 
        
        #This isn't really needed but makes a bunch of stuff clearer
        self.action_id2w = {0: 'left', 1: 'right', 2: 'up', 3:'down', 4:'no_action'}
        self.action_w2id = {v:k for k,v in self.action_id2w.items()}
        
        self.agents = [Agent(i, self.action_id2w, self.action_w2id) for i in range(self.num_robots)]
        for i, a in enumerate(self.agents):
            if i % 2 == 0: #Even numbered agents are assigned the green zone
                a.goal = 'Green'

        #Initializes the action and observation spaces
        actions = []
        observations = []
        for a in self.agents:
            actions.append(spaces.Discrete(5))
            #each agent's observation is a tuple of size 3
            obs_dim = self.agent_obs_dim * (self.args.num_neighbors + 1)
            #the minimum observation is the left corner of the robotarium, the maximum is the righ corner
            observations.append(spaces.Box(low=-1.5, high=1.5, shape=(obs_dim,), dtype=np.float32))
        self.action_space = spaces.Tuple(tuple(actions))
        self.observation_space = spaces.Tuple(tuple(observations))
        
        self.visualizer = Visualize(self.args) #needed for Robotarium renderings
        #Env impliments the robotarium backend
        #It expects to have access to agent_poses, visualizer, num_agents and _generate_step_goal_positions
        self.env = roboEnv(self, args)  

    def reset(self):
        self.episode_steps = 0
        for a in self.agents:
            a.loaded=False
        
        #Generate the agent locations based on the config
        width = self.args.RIGHT - self.args.LEFT
        height = self.args.DOWN - self.args.UP
        #Agents can spawn anywhere in the Robotarium between UP, DOWN, LEFT and RIGHT for this scenario
        self.agent_poses = generate_initial_conditions(self.num_robots, spacing=self.args.START_DIST, width=width, height=height)
        #Adjusts the poses based on the config
        self.agent_poses[0] += (1.5 + self.args.LEFT)/2
        self.agent_poses[0] -= (1.5 - self.args.RIGHT)/2
        self.agent_poses[1] -= (1+self.args.UP)/2
        self.agent_poses[1] += (1-self.args.DOWN)/2
        self.env.reset()
        return [[0]*(self.agent_obs_dim * (self.args.num_neighbors + 1))] * self.num_robots
    
    def step(self, actions_):
        self.episode_steps += 1

        #Robotarium actions and updating agent_poses all happen here
        self.env.step(actions_) 

        rewards = self.get_rewards()
        obs = self.get_observations()
        terminated = self.episode_steps > self.args.max_episode_steps #For this environment, episode only ends after timing out
        
        return obs, rewards, [terminated]*self.num_robots, {}
    
    def get_observations(self):
        observations = [] #Each agent's individual observation
        for a in self.agents:
            observations.append([*self.agent_poses[:, a.index ][:2], a.loaded])

        #Get each agent's observations concatenated with args.num_neighbors nearest neighbors
        #Or all of the agent's observations within args.delta radius if args.delta>0
        full_observations = []
        for i, agent in enumerate(self.agents):
            full_observations.append(observations[agent.index])
            
            # For getting neighbors in delta radius. Not being used right now to avoid inconsistent observation dimensions
            if self.args.delta > 0:
                nbr_indices = delta_disk_neighbors(self.agent_poses,agent.index,self.args.delta)
            elif self.args.num_neighbors >= self.num_robots-1:
                nbr_indices = [i for i in range(self.num_robots) if i != agent.index]
            else:
                nbr_indices = get_nearest_neighbors(self.agent_poses, agent.index, self.args.num_neighbors)
            
            # full_observation[i] is of dimension [NUM_NBRS, OBS_DIM]
            for nbr_index in nbr_indices:
                full_observations[i] = np.concatenate( (full_observations[i],observations[nbr_index]) )
        return full_observations

    def get_rewards(self):
        '''
        If loaded the agents score by driving to their color zone on the left
        If unloaded the agents score by driving to their color zone on the right
        Kind of like robots that have to move stuff around at a warehouse
        '''
        rewards = []
        for a in self.agents:
            pos = self.agent_poses[:, a.index ][:2]
            if a.loaded:             
                if pos[0] < -1.5 + self.args.goal_width:
                    if a.goal == 'Green' and pos[1] > 0:
                        rewards.append(self.args.unload_reward)
                        a.loaded = False
                    elif a.goal == 'Red' and pos[1] <= 0:
                        rewards.append(self.args.unload_reward)
                        a.loaded = False
                    else:
                        rewards.append(0)
                else:
                    rewards.append(0)
            else:
                if pos[0] > 1.5 - self.args.goal_width:
                    if a.goal == 'Red' and pos[1] > 0:
                        rewards.append(self.args.load_reward)
                        a.loaded = True
                    elif a.goal == 'Green' and pos[1] <= 0:
                        rewards.append(self.args.load_reward)
                        a.loaded = True
                    else:
                        rewards.append(0)
                else:
                    rewards.append(0)
        return rewards

    def _generate_step_goal_positions(self, actions):
        '''
        User implemented
        Calculates the goal locations for the current agent poses and actions
        returns an array of the robotarium positions that it is trying to reach
        '''
        goal = copy.deepcopy(self.agent_poses)
        for i, agent in enumerate(self.agents):
            goal[:,i] = agent.generate_goal(goal[:,i], actions[i], self.args)
        
        return goal

    def get_observation_space(self):
        return self.observation_space

    def get_action_space(self):
        return self.action_space