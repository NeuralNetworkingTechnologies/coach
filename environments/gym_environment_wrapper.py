#
# Copyright (c) 2017 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import sys
from logger import *
import gym
import numpy as np
import time
try:
    import roboschool
    from OpenGL import GL
except ImportError:
    from logger import failed_imports
    failed_imports.append("RoboSchool")

try:
    from gym_extensions.continuous import mujoco
except:
    from logger import failed_imports
    failed_imports.append("GymExtensions")

try:
    import pybullet_envs
except ImportError:
    from logger import failed_imports
    failed_imports.append("PyBullet")

from gym import wrappers
from utils import force_list, RunPhase
from environments.environment_wrapper import EnvironmentWrapper


class GymEnvironmentWrapper(EnvironmentWrapper):
    def __init__(self, tuning_parameters):
        EnvironmentWrapper.__init__(self, tuning_parameters)

        # env parameters
        if ':' in self.env_id:
            self.env = gym.envs.registration.load(self.env_id)()
        else:
            self.env = gym.make(self.env_id)

        if self.seed is not None:
            self.env.seed(self.seed)

        # self.env_spec = gym.spec(self.env_id)
        self.env.frameskip = self.frame_skip
        self.discrete_controls = type(self.env.action_space) != gym.spaces.box.Box

        self.observation = self.reset(True)['observation']

        # render
        if self.is_rendered:
            image = self.get_rendered_image()
            scale = 1
            if self.human_control:
                scale = 2
            self.renderer.create_screen(image.shape[1]*scale, image.shape[0]*scale)

        self.is_state_type_image = len(self.observation.shape) > 1
        if self.is_state_type_image:
            self.width = self.observation.shape[1]
            self.height = self.observation.shape[0]
        else:
            self.width = self.observation.shape[0]

        # action space
        self.actions_description = {}
        if hasattr(self.env.unwrapped, 'get_action_meanings'):
            self.actions_description = self.env.unwrapped.get_action_meanings()
        if self.discrete_controls:
            self.action_space_size = self.env.action_space.n
            self.action_space_abs_range = 0
        else:
            self.action_space_size = self.env.action_space.shape[0]
            self.action_space_high = self.env.action_space.high
            self.action_space_low = self.env.action_space.low
            self.action_space_abs_range = np.maximum(np.abs(self.action_space_low), np.abs(self.action_space_high))
        self.actions = {i: i for i in range(self.action_space_size)}
        self.key_to_action = {}
        if hasattr(self.env.unwrapped, 'get_keys_to_action'):
            self.key_to_action = self.env.unwrapped.get_keys_to_action()

        # measurements
        if self.env.spec is not None:
            self.timestep_limit = self.env.spec.timestep_limit
        else:
            self.timestep_limit = None
        self.measurements_size = len(self.step(0)['info'].keys())

    def _update_state(self):
        if hasattr(self.env, 'env') and hasattr(self.env.env, 'ale'):
            if self.phase == RunPhase.TRAIN and hasattr(self, 'current_ale_lives'):
                # signal termination for life loss
                if self.current_ale_lives != self.env.env.ale.lives():
                    self.done = True
            self.current_ale_lives = self.env.env.ale.lives()

    def _take_action(self, action_idx):
        if action_idx is None:
            action_idx = self.last_action_idx

        if self.discrete_controls:
            action = self.actions[action_idx]
        else:
            action = action_idx

        # pendulum-v0 for example expects a list
        if not self.discrete_controls:
            # catching cases where the action for continuous control is a number instead of a list the
            # size of the action space
            if type(action_idx) == int and action_idx == 0:
                # deal with the "reset" action 0
                action = [0] * self.env.action_space.shape[0]
            action = np.array(force_list(action))
            # removing redundant dimensions such that the action size will match the expected action size from gym
            if action.shape != self.env.action_space.shape:
                action = np.squeeze(action)
            action = np.clip(action, self.action_space_low, self.action_space_high)

        self.observation, self.reward, self.done, self.info = self.env.step(action)

    def _preprocess_observation(self, observation):
        if any(env in self.env_id for env in ["Breakout", "Pong"]):
            # crop image
            observation = observation[34:195, :, :]
        return observation

    def _restart_environment_episode(self, force_environment_reset=False):
        # prevent reset of environment if there are ale lives left
        if (hasattr(self.env, 'env') and hasattr(self.env.env, 'ale') and self.env.env.ale.lives() > 0) \
                and not force_environment_reset and not self.env._past_limit():
            return self.observation

        if self.seed:
            self.env.seed(self.seed)

        self.observation = self.env.reset()
        while self.observation is None:
            self.step(0)

        return self.observation

    def get_rendered_image(self):
        return self.env.render(mode='rgb_array')
