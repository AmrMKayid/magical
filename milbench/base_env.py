"""Gym wrapper for shape-pushing environment."""

import abc
import functools
import inspect

import gym
from gym import spaces
from gym.utils import EzPickle
import numpy as np
import pymunk as pm

import milbench.entities as en
import milbench.gym_render as r
from milbench.phys_vars import PhysicsVariablesBase, PhysVar


def ez_init(*args, **kwargs):
    """Decorator to initialise EzPickle from all arguments and keyword
    arguments. Use it like this:

        class C(…, EzPickle):
            @ez_init()
            def __init__(self, spam, ham, …):
                …"""
    assert len(args) == 0 and len(kwargs) == 0, \
        "ez_init takes no args at the moment (use `@ez_init()` only)"

    def inner_decorator(method):
        # sanity checks
        msg = f"Got function {method}; should only be used to decorate " \
              f"__init__() methods of classes"
        assert inspect.isfunction(method), msg
        assert method.__name__ == '__init__', msg

        @functools.wraps(method)
        def wrapper(*args, **kwargs):
            self_var = args[0]
            EzPickle.__init__(self_var, *args[1:], **kwargs)
            return method(*args, **kwargs)

        return wrapper

    return inner_decorator


class PhysicsVariables(PhysicsVariablesBase):
    """Default values & randomisation ranges for key physical parameters of the
    environment."""
    # robot_pos_joint_max_force = PhysVar(3, (2.5, 4))
    robot_pos_joint_max_force = PhysVar(3, (2.2, 3.5))
    robot_rot_joint_max_force = PhysVar(1, (0.7, 1.5))
    robot_finger_max_force = PhysVar(4, (2.5, 4.5))
    shape_trans_joint_max_force = PhysVar(1.5, (1.0, 1.8))
    shape_rot_joint_max_force = PhysVar(0.1, (0.07, 0.15))


class BaseEnv(gym.Env, abc.ABC):
    # constants for all envs
    ROBOT_RAD = 0.2
    ROBOT_MASS = 1.0
    SHAPE_RAD = ROBOT_RAD * 3 / 5
    ARENA_BOUNDS_LRBT = [-1, 1, -1, 1]
    ARENA_SIZE_MAX = max(ARENA_BOUNDS_LRBT)
    # minimum and maximum size of goal regions used during randomisation
    RAND_GOAL_MIN_SIZE = 0.5
    RAND_GOAL_MAX_SIZE = 0.8
    RAND_GOAL_SIZE_RANGE = RAND_GOAL_MAX_SIZE - RAND_GOAL_MIN_SIZE
    # the following are used to standardise what "jitter" means across
    # different tasks
    JITTER_PCT = 0.05
    JITTER_POS_BOUND = ARENA_SIZE_MAX * JITTER_PCT / 2.0
    JITTER_ROT_BOUND = JITTER_PCT * np.pi
    JITTER_TARGET_BOUND = JITTER_PCT * RAND_GOAL_SIZE_RANGE / 2

    def __init__(self,
                 *,
                 res_hw=(256, 256),
                 fps=20,
                 phys_steps=10,
                 phys_iter=10,
                 max_episode_steps=None,
                 rand_dynamics=False):
        self.phys_iter = phys_iter
        self.phys_steps = phys_steps
        self.fps = fps
        self.res_hw = res_hw
        self.max_episode_steps = max_episode_steps
        # RGB observation, stored as bytes
        self.observation_space = spaces.Box(low=0.0,
                                            high=255,
                                            shape=(*res_hw, 3),
                                            dtype=np.uint8)
        # action space includes every combination of those
        self.action_space = spaces.Discrete(len(en.ACTION_NUMS_FLAGS_NAMES))

        # state/rendering (see reset())
        self._entities = None
        self._space = None
        self._robot = None
        self._episode_steps = None
        self._phys_vars = None
        # this is for background rendering
        self.viewer = None
        # common randomisation option for all envs
        self.rand_dynamics = rand_dynamics

        self.seed()

    def action_to_flags(self, int_action):
        """Parse a 'flat' integer action into a combination of flags."""
        return en.ACTION_ID_TO_FLAGS[int(int_action)]

    def flags_to_action(self, flags):
        """Convert a 'structured' list of flags into a single flag integer
        action. Inverse of action_to_flags."""
        return en.FLAGS_TO_ACTION_ID[tuple(flags)]

    def seed(self, seed=None):
        """Initialise the PRNG and return seed necessary to reproduce results.

        (TODO: should I also seed action/observation spaces? Not clear.)"""
        if seed is None:
            seed = np.random.randint(0, (1 << 31) - 1)
        self.rng = np.random.RandomState(seed=seed)
        return [seed]

    def _make_robot(self, init_pos, init_angle):
        return en.Robot(radius=self.ROBOT_RAD,
                        init_pos=init_pos,
                        init_angle=init_angle,
                        mass=self.ROBOT_MASS)

    def _make_shape(self, **kwargs):
        return en.Shape(shape_size=self.SHAPE_RAD, **kwargs)

    @classmethod
    @abc.abstractmethod
    def make_name(cls, suffix=None):
        """Return a name for an env based on this one, but using the supplied
        suffix. For instance, if an environment were called 'CircleMove' and
        its version were v0, then env_cls.make_name('Hard') would return
        'CircleMoveHard-v0'. If no suffix is supplied then it will just return
        the base name with a version.

        Args:
            suffix (str): the suffix to append to the base name for this
            env.

        Returns:
            name (str): full, Gym-compatible name for this env, with the
                included name suffix."""
        pass

    @abc.abstractmethod
    def on_reset(self):
        """Set up entities necessary for this environment, and reset any other
        data needed for the env. Must create a robot in addition to any
        necessary entities, and return bot hthe robot and the other entities
        separately.

        Returns: a tuple with the following elements:
            robot (en.Robot): an initialised robot to be controlled by the
                user.
            ents ([en.Entity]): list of other entities necessary for this
                environment."""
        pass

    def add_entities(self, entities):
        """Adds a list of entities to the current entities list and sets it up.
        Only intended to be used from within on_reset(). Needs to be called for
        every created entity or else they will not be added to the space!

        Args:
            entities (en.Entity): the entity to add."""
        for entity in entities:
            if isinstance(entity, en.Robot):
                self._robot = entity
            self._entities.append(entity)
            entity.setup(self.viewer, self._space, self._phys_vars)

    def reset(self):
        self._episode_steps = 0
        # delete old entities/space
        self._entities = []
        self._space = None
        self._robot = None
        self._phys_vars = None
        if self.viewer is None:
            res_h, res_w = self.res_hw
            self.viewer = r.Viewer(res_w, res_h, visible=False)
        else:
            # these will get added back later
            self.viewer.reset_geoms()
        self._space = pm.Space()
        self._space.collision_slop = 0.01
        self._space.iterations = self.phys_iter

        if self.rand_dynamics:
            # Randomise the physics properties of objects and the robot a
            # little bit.
            self._phys_vars = PhysicsVariables.sample(self.rng)
        else:
            self._phys_vars = PhysicsVariables.defaults()

        # set up robot and arena
        arena_l, arena_r, arena_b, arena_t = self.ARENA_BOUNDS_LRBT
        self._arena = en.ArenaBoundaries(left=arena_l,
                                         right=arena_r,
                                         bottom=arena_b,
                                         top=arena_t)
        self.add_entities([self._arena])
        reset_rv = self.on_reset()
        assert reset_rv is None, \
            f"on_reset method of {type(self)} returned {reset_rv}, but "\
            f"should return None"
        assert isinstance(self._robot, en.Robot)
        assert len(self._entities) >= 1

        self.viewer.set_bounds(left=self._arena.left,
                               right=self._arena.right,
                               bottom=self._arena.bottom,
                               top=self._arena.top)

        # # step forward by one second so PyMunk can recover from bad initial
        # # conditions
        # forward_time = 1.0
        # forward_frames = int(math.ceil(forward_time * self.fps))
        # for _ in range(forward_frames):
        #     self._phys_steps_on_frame()

        return self.render(mode='rgb_array')

    def _phys_steps_on_frame(self):
        phys_steps = 10
        spf = 1 / self.fps
        dt = spf / phys_steps
        for i in range(phys_steps):
            for ent in self._entities:
                ent.update(dt)
            self._space.step(dt)

    @abc.abstractmethod
    def score_on_end_of_traj(self):
        """Compute the score for this trajectory. Only called at the last step
        of the trajectory.

        Returns:
           score (float): number in [0, 1] indicating the worst possible
               performance (0), the best possible performance (1) or something
               in between. Should apply to the WHOLE trajectory."""
        pass

    def step(self, action):
        # step forward physics
        ac_flag_ud, ac_flag_lr, ac_flag_grip = self.action_to_flags(action)
        action_flag = en.RobotAction.NONE
        action_flag |= ac_flag_ud
        action_flag |= ac_flag_lr
        action_flag |= ac_flag_grip
        self._robot.set_action(action_flag)
        self._phys_steps_on_frame()

        info = {}
        # always 0 reward (avoids training RL algs accidentally)
        reward = 0.0

        # check episode step count
        self._episode_steps += 1
        done = False
        eval_score = 0.0
        if self.max_episode_steps is not None:
            done = done or self._episode_steps >= self.max_episode_steps
        if done:
            eval_score = self.score_on_end_of_traj()
            assert 0 <= eval_score <= 1, \
                f'eval score {eval_score} out of range for env {self}'
            # These were my attempts at sneaking episode termination info
            # through the Monitor and SubprocVecEnv wrappers ('monitor_info'
            # was a keyword I gave to info_keywords in the Monitor
            # constructor). I don't know why, but neither approach worked.
            # info['monitor_info'] = end_ep_dict
            # info['episode'] = end_ep_dict
        # we *always* include a score, even if it's zero, because at least one
        # RL framework (rlpyt) refuses to recognise keys that aren't present at
        # the first time step.
        info.update(eval_score=eval_score)

        obs_u8 = self.render(mode='rgb_array')

        return obs_u8, reward, done, info

    def render(self, mode='human'):
        if self.viewer is None:
            return None
        for ent in self._entities:
            ent.pre_draw()
        if mode == 'human':
            self.viewer.window.set_visible(True)
        else:
            assert mode == 'rgb_array'
        return self.viewer.render(return_rgb_array=True)

    def close(self):
        if self.viewer:
            self.viewer.close()
            self.viewer = None
