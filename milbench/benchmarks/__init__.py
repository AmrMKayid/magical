"""Register available envs and create index of train/test mappings."""

import collections
import functools
import re

import gym
from gym.spaces import Box
from gym.wrappers import FrameStack, GrayScaleObservation, ResizeObservation
import numpy as np

from milbench.benchmarks.cluster import ClusterColourEnv, ClusterShapeEnv
from milbench.benchmarks.find_dupe import FindDupeEnv
from milbench.benchmarks.fix_colour import FixColourEnv
from milbench.benchmarks.make_line import MakeLineEnv
from milbench.benchmarks.match_regions import MatchRegionsEnv
from milbench.benchmarks.move_to_corner import MoveToCornerEnv
from milbench.benchmarks.move_to_region import MoveToRegionEnv

__all__ = [
    'DEMO_ENVS_TO_TEST_ENVS_MAP',
    'MoveToCornerEnv',
    'MatchRegionsEnv',
    'ClusterColourEnv',
    'ClusterShapeEnv',
    'FindDupeEnv',
    'MakeLineEnv',
    'register_envs',
    'EnvName',
]

DEFAULT_RES = (384, 384)


class EagerFrameStack(FrameStack):
    """Variant of FrameStack that concatenates along the last (channels)
    axis."""
    def __init__(self, env, num_stack):
        super().__init__(env, num_stack, lz4_compress=False)
        old_shape = env.observation_space.shape
        assert len(old_shape) == 3 and old_shape[-1] in {3, 1}, \
            f"expected old shape to be 3D tensor with RGB or greyscale " \
            f"colour axis at end, but got shape {old_shape}"
        low = np.repeat(env.observation_space.low, num_stack, axis=-1)
        high = np.repeat(env.observation_space.high, num_stack, axis=-1)
        self.observation_space = Box(low=low,
                                     high=high,
                                     dtype=self.observation_space.dtype)

    def _get_observation(self):
        assert len(self.frames) == self.num_stack, \
            (len(self.frames), self.num_stack)
        return np.concatenate(self.frames, axis=-1)


def lores_stack_entry_point(env_cls, small_res, frames=4, greyscale=False):
    def make_lores_stack(**kwargs):
        base_env = env_cls(**kwargs)
        if greyscale:
            col_env = GrayScaleObservation(base_env, keep_dim=True)
        else:
            col_env = base_env
        resize_env = ResizeObservation(col_env, small_res)
        stack_env = EagerFrameStack(resize_env, frames)
        return stack_env

    return make_lores_stack


DEFAULT_PREPROC_ENTRY_POINT_WRAPPERS = collections.OrderedDict([
    # Images downsampled to 96x96 four adjacent frames stacked together. That
    # is about the smallest size at which you can distinguish pentagon vs.
    # hexagon vs. circle. It's also about 20% as many pixels as an ImageNet
    # network, so should be reasonably memory-efficient to train.
    ('LoResStack',
     functools.partial(lores_stack_entry_point, small_res=(96, 96), frames=4)),
    # This next one is only intended for debugging RL algorithms. The images
    # are too small to resolve, e.g., octagons vs. circles, and it also omits
    # colour, which is necessary for some tasks.
    ('AtariStyle',
     functools.partial(lores_stack_entry_point,
                       small_res=(84, 84),
                       frames=4,
                       greyscale=True)),
])
_ENV_NAME_RE = re.compile(
    r'^(?P<name_prefix>[^-]+)(?P<demo_test_spec>-(Demo|Test[^-]*))'
    r'(?P<env_name_suffix>(-[^-]+)*)(?P<version_suffix>-v\d+)$')
_REGISTERED = False
# this will be filled in later
DEMO_ENVS_TO_TEST_ENVS_MAP = collections.OrderedDict()


class EnvName:
    """Convenience class for parsing environment names. All environment names
    look like this (per _ENV_NAME_RE):

        <name_prefix>-<demo_test_spec>[-<suffix>]-<version_suffix>

    Where:
        - name_prefix identifies the environment class (e.g. MoveToCorner).
        - demo_test_spec is either 'demo' for the demonstration environment, or
          'Test<description>' for test environments, where the description is
          something like 'Pose' or 'Colour' or 'All', depending on what aspects
          of the environment are randomised.
        - suffix is usually for indicating a type of postprocessing (e.g.
          -LoResStack for stacked, scaled-down frames). Not always present.
        - version_suffix is -v0, -v1, etc. etc."""
    def __init__(self, env_name):
        match = _ENV_NAME_RE.match(env_name)
        if match is None:
            raise ValueError(
                "env name '{env_name}' does not match _ENV_NAME_RE spec")
        groups = match.groupdict()
        self.env_name = env_name
        self.name_prefix = groups['name_prefix']
        self.demo_test_spec = groups['demo_test_spec']
        self.env_name_suffix = groups['env_name_suffix']
        self.version_suffix = groups['version_suffix']
        self.demo_env_name = self.name_prefix + '-Demo' \
            + self.env_name_suffix + self.version_suffix
        self.is_test = self.demo_test_spec.startswith('-Test')
        if not self.is_test:
            assert self.demo_env_name == self.env_name, \
                (self.demo_env_name, self.env_name)


def register_envs():
    """Register all default environments for this benchmark suite."""
    global _REGISTERED, DEMO_ENVS_TO_TEST_ENVS_MAP
    if _REGISTERED:
        return False
    _REGISTERED = True

    common_kwargs = dict(res_hw=DEFAULT_RES,
                         fps=8,
                         phys_steps=10,
                         phys_iter=10)

    # remember 100 frames is ~12.5s at 8fps
    mtc_ep_len = 80
    move_to_corner_variants = [
        (MoveToCornerEnv, mtc_ep_len, '-Demo', {
            'rand_shape_colour': False,
            'rand_shape_type': False,
            'rand_poses': False,
            'rand_dynamics': False,
        }),
        (MoveToCornerEnv, mtc_ep_len, '-TestColour', {
            'rand_shape_colour': True,
            'rand_shape_type': False,
            'rand_poses': False,
            'rand_dynamics': False,
        }),
        (MoveToCornerEnv, mtc_ep_len, '-TestShape', {
            'rand_shape_colour': False,
            'rand_shape_type': True,
            'rand_poses': False,
            'rand_dynamics': False,
        }),
        (MoveToCornerEnv, mtc_ep_len, '-TestJitter', {
            'rand_shape_colour': False,
            'rand_shape_type': False,
            'rand_poses': True,
            'rand_dynamics': False,
        }),
        (MoveToCornerEnv, mtc_ep_len, '-TestDynamics', {
            'rand_shape_colour': False,
            'rand_shape_type': False,
            'rand_poses': False,
            'rand_dynamics': True,
        }),
        (MoveToCornerEnv, mtc_ep_len, '-TestAll', {
            'rand_shape_colour': True,
            'rand_shape_type': True,
            'rand_poses': True,
            'rand_dynamics': True,
        }),
    ]

    mtr_ep_len = 40
    move_to_region_variants = [
        (MoveToRegionEnv, mtr_ep_len, '-Demo', {
            'rand_poses_minor': False,
            'rand_poses_full': False,
            'rand_goal_colour': False,
            'rand_dynamics': False,
        }),
        (MoveToRegionEnv, mtr_ep_len, '-TestJitter', {
            'rand_poses_minor': True,
            'rand_poses_full': False,
            'rand_goal_colour': False,
            'rand_dynamics': False,
        }),
        (MoveToRegionEnv, mtr_ep_len, '-TestColour', {
            'rand_poses_minor': False,
            'rand_poses_full': False,
            'rand_goal_colour': True,
            'rand_dynamics': False,
        }),
        (MoveToRegionEnv, mtr_ep_len, '-TestLayout', {
            'rand_poses_minor': False,
            'rand_poses_full': True,
            'rand_goal_colour': False,
            'rand_dynamics': False,
        }),
        (MoveToRegionEnv, mtr_ep_len, '-TestDynamics', {
            'rand_poses_minor': False,
            'rand_poses_full': False,
            'rand_goal_colour': False,
            'rand_dynamics': True,
        }),
        (MoveToRegionEnv, mtr_ep_len, '-TestAll', {  # to stop yapf
            'rand_poses_minor': False,
            # rand_poses_full subsumes rand_poses_minor
            'rand_poses_full': True,
            'rand_goal_colour': True,
            'rand_dynamics': True,
        }),
        # FIXME: this is just a test env for egocentric observations; if this
        # works, then I should add egocentric views as an option in the same
        # way that I've added frame stacking etc. (ideal: combine egocentric
        # views AND a global view!)
        (MoveToRegionEnv, mtr_ep_len, '-TestEgo', {
            'rand_poses_minor': False,
            'rand_poses_full': False,
            'rand_goal_colour': False,
            'rand_dynamics': False,
            'egocentric': True,
        }),
    ]

    mr_ep_len = 120
    match_regions_variants = [
        (MatchRegionsEnv, mr_ep_len, '-Demo', {
            'rand_target_colour': False,
            'rand_shape_type': False,
            'rand_shape_count': False,
            'rand_layout_minor': False,
            'rand_layout_full': False,
            'rand_dynamics': False,
        }),
        (MatchRegionsEnv, mr_ep_len, '-TestJitter', {
            'rand_target_colour': False,
            'rand_shape_type': False,
            'rand_shape_count': False,
            'rand_layout_minor': True,
            'rand_layout_full': False,
            'rand_dynamics': False,
        }),
        (MatchRegionsEnv, mr_ep_len, '-TestColour', {
            'rand_target_colour': True,
            'rand_shape_type': False,
            'rand_shape_count': False,
            'rand_layout_minor': False,
            'rand_layout_full': False,
            'rand_dynamics': False,
        }),
        (MatchRegionsEnv, mr_ep_len, '-TestShape', {
            'rand_target_colour': False,
            'rand_shape_type': True,
            'rand_shape_count': False,
            'rand_layout_minor': False,
            'rand_layout_full': False,
            'rand_dynamics': False,
        }),
        (MatchRegionsEnv, mr_ep_len, '-TestLayout', {
            'rand_target_colour': False,
            'rand_shape_type': False,
            'rand_shape_count': False,
            'rand_layout_minor': False,
            'rand_layout_full': True,
            'rand_dynamics': False,
        }),
        # test everything except dynamics
        (MatchRegionsEnv, mr_ep_len, '-TestCountPlus', {
            'rand_target_colour': True,
            'rand_shape_type': True,
            'rand_shape_count': True,
            'rand_layout_minor': False,
            'rand_layout_full': True,
            'rand_dynamics': False,
        }),
        (MatchRegionsEnv, mr_ep_len, '-TestDynamics', {
            'rand_target_colour': False,
            'rand_shape_type': False,
            'rand_shape_count': False,
            'rand_layout_minor': False,
            'rand_layout_full': False,
            'rand_dynamics': True,
        }),
        (MatchRegionsEnv, mr_ep_len, '-TestAll', {
            'rand_target_colour': True,
            'rand_shape_type': True,
            'rand_shape_count': True,
            'rand_layout_minor': False,
            'rand_layout_full': True,
            'rand_dynamics': True,
        }),
    ]

    ml_ep_len = 180
    make_line_variants = [
        (MakeLineEnv, ml_ep_len, '-Demo', {
            'rand_colours': False,
            'rand_shapes': False,
            'rand_count': False,
            'rand_layout_minor': False,
            'rand_layout_full': False,
            'rand_dynamics': False,
        }),
        (MakeLineEnv, ml_ep_len, '-TestJitter', {
            'rand_colours': False,
            'rand_shapes': False,
            'rand_count': False,
            'rand_layout_minor': True,
            'rand_layout_full': False,
            'rand_dynamics': False,
        }),
        (MakeLineEnv, ml_ep_len, '-TestColour', {
            'rand_colours': True,
            'rand_shapes': False,
            'rand_count': False,
            'rand_layout_minor': False,
            'rand_layout_full': False,
            'rand_dynamics': False,
        }),
        (MakeLineEnv, ml_ep_len, '-TestShape', {
            'rand_colours': False,
            'rand_shapes': True,
            'rand_count': False,
            'rand_layout_minor': False,
            'rand_layout_full': False,
            'rand_dynamics': False,
        }),
        (MakeLineEnv, ml_ep_len, '-TestLayout', {
            'rand_colours': False,
            'rand_shapes': False,
            'rand_count': False,
            'rand_layout_minor': False,
            'rand_layout_full': True,
            'rand_dynamics': False,
        }),
        # test everything except dynamics
        (MakeLineEnv, ml_ep_len, '-TestCountPlus', {
            'rand_colours': True,
            'rand_shapes': True,
            'rand_count': True,
            'rand_layout_minor': False,
            'rand_layout_full': True,
            'rand_dynamics': False,
        }),
        (MakeLineEnv, ml_ep_len, '-TestDynamics', {
            'rand_colours': False,
            'rand_shapes': False,
            'rand_count': False,
            'rand_layout_minor': False,
            'rand_layout_full': False,
            'rand_dynamics': True,
        }),
        (MakeLineEnv, ml_ep_len, '-TestAll', {
            'rand_colours': True,
            'rand_shapes': True,
            'rand_count': True,
            'rand_layout_minor': False,
            'rand_layout_full': True,
            'rand_dynamics': True,
        }),
    ]

    fd_ep_len = 100
    find_dupe_variants = [
        (FindDupeEnv, fd_ep_len, '-Demo', {
            'rand_colours': False,
            'rand_shapes': False,
            'rand_count': False,
            'rand_layout_minor': False,
            'rand_layout_full': False,
            'rand_dynamics': False,
        }),
        (FindDupeEnv, fd_ep_len, '-TestJitter', {
            'rand_colours': False,
            'rand_shapes': False,
            'rand_count': False,
            'rand_layout_minor': True,
            'rand_layout_full': False,
            'rand_dynamics': False,
        }),
        (FindDupeEnv, fd_ep_len, '-TestColour', {
            'rand_colours': True,
            'rand_shapes': False,
            'rand_count': False,
            'rand_layout_minor': False,
            'rand_layout_full': False,
            'rand_dynamics': False,
        }),
        (FindDupeEnv, fd_ep_len, '-TestShape', {
            'rand_colours': False,
            'rand_shapes': True,
            'rand_count': False,
            'rand_layout_minor': False,
            'rand_layout_full': False,
            'rand_dynamics': False,
        }),
        (FindDupeEnv, fd_ep_len, '-TestLayout', {
            'rand_colours': False,
            'rand_shapes': False,
            'rand_count': False,
            'rand_layout_minor': False,
            'rand_layout_full': True,
            'rand_dynamics': False,
        }),
        (FindDupeEnv, fd_ep_len, '-TestCountPlus', {
            'rand_colours': True,
            'rand_shapes': True,
            'rand_count': True,
            'rand_layout_minor': False,
            'rand_layout_full': True,
            'rand_dynamics': False,
        }),
        (FindDupeEnv, fd_ep_len, '-TestDynamics', {
            'rand_colours': False,
            'rand_shapes': False,
            'rand_count': False,
            'rand_layout_minor': False,
            'rand_layout_full': False,
            'rand_dynamics': True,
        }),
        (FindDupeEnv, fd_ep_len, '-TestAll', {
            'rand_colours': True,
            'rand_shapes': True,
            'rand_count': True,
            'rand_layout_minor': False,
            'rand_layout_full': True,
            'rand_dynamics': True,
        }),
    ]

    fc_ep_len = 60
    fix_colour_variants = [
        (FixColourEnv, fc_ep_len, '-Demo', {
            'rand_colours': False,
            'rand_shapes': False,
            'rand_count': False,
            'rand_layout_minor': False,
            'rand_layout_full': False,
            'rand_dynamics': False,
        }),
        (FixColourEnv, fc_ep_len, '-TestJitter', {
            'rand_colours': False,
            'rand_shapes': False,
            'rand_count': False,
            'rand_layout_minor': True,
            'rand_layout_full': False,
            'rand_dynamics': False,
        }),
        (FixColourEnv, fc_ep_len, '-TestColour', {
            'rand_colours': True,
            'rand_shapes': False,
            'rand_count': False,
            'rand_layout_minor': False,
            'rand_layout_full': False,
            'rand_dynamics': False,
        }),
        (FixColourEnv, fc_ep_len, '-TestShape', {
            'rand_colours': False,
            'rand_shapes': True,
            'rand_count': False,
            'rand_layout_minor': False,
            'rand_layout_full': False,
            'rand_dynamics': False,
        }),
        (FixColourEnv, fc_ep_len, '-TestLayout', {
            'rand_colours': False,
            'rand_shapes': False,
            'rand_count': False,
            'rand_layout_minor': False,
            'rand_layout_full': True,
            'rand_dynamics': False,
        }),
        (FixColourEnv, fc_ep_len, '-TestCountPlus', {
            'rand_colours': True,
            'rand_shapes': True,
            'rand_count': True,
            'rand_layout_minor': False,
            'rand_layout_full': True,
            'rand_dynamics': False,
        }),
        (FixColourEnv, fc_ep_len, '-TestDynamics', {
            'rand_colours': False,
            'rand_shapes': False,
            'rand_count': False,
            'rand_layout_minor': False,
            'rand_layout_full': False,
            'rand_dynamics': True,
        }),
        (FixColourEnv, fc_ep_len, '-TestAll', {
            'rand_colours': True,
            'rand_shapes': True,
            'rand_count': True,
            'rand_layout_minor': False,
            'rand_layout_full': True,
            'rand_dynamics': True,
        }),
    ]

    # Long episodes because this is a hard environment. You can have up to 10
    # blocks when doing random layouts, and that takes a human 20-30s to
    # process (so 240/8=30s is just enough time to finish a 10-block run if
    # you know what you're doing).
    cluster_ep_len = 240
    cluster_variants = []
    for cluster_cls in (ClusterColourEnv, ClusterShapeEnv):
        cluster_variants.extend([
            (cluster_cls, cluster_ep_len, '-Demo', {
                'rand_shape_colour': False,
                'rand_shape_type': False,
                'rand_layout_minor': False,
                'rand_layout_full': False,
                'rand_shape_count': False,
                'rand_dynamics': False,
            }),
            (cluster_cls, cluster_ep_len, '-TestJitter', {
                'rand_shape_colour': False,
                'rand_shape_type': False,
                'rand_layout_minor': True,
                'rand_layout_full': False,
                'rand_shape_count': False,
                'rand_dynamics': False,
            }),
            (cluster_cls, cluster_ep_len, '-TestColour', {
                'rand_shape_colour': True,
                'rand_shape_type': False,
                'rand_layout_minor': False,
                'rand_layout_full': False,
                'rand_shape_count': False,
                'rand_dynamics': False,
            }),
            (cluster_cls, cluster_ep_len, '-TestShape', {
                'rand_shape_colour': False,
                'rand_shape_type': True,
                'rand_layout_minor': False,
                'rand_layout_full': False,
                'rand_shape_count': False,
                'rand_dynamics': False,
            }),
            (cluster_cls, cluster_ep_len, '-TestLayout', {
                'rand_shape_colour': False,
                'rand_shape_type': False,
                'rand_layout_minor': False,
                'rand_layout_full': True,
                'rand_shape_count': False,
                'rand_dynamics': False,
            }),
            (cluster_cls, cluster_ep_len, '-TestCountPlus', {
                'rand_shape_colour': True,
                'rand_shape_type': True,
                'rand_layout_minor': False,
                'rand_layout_full': True,
                'rand_shape_count': True,
                'rand_dynamics': False,
            }),
            (cluster_cls, cluster_ep_len, '-TestDynamics', {
                'rand_shape_colour': False,
                'rand_shape_type': False,
                'rand_layout_minor': False,
                'rand_layout_full': False,
                'rand_shape_count': False,
                'rand_dynamics': True,
            }),
            (cluster_cls, cluster_ep_len, '-TestAll', {
                'rand_shape_colour': True,
                'rand_shape_type': True,
                'rand_layout_minor': False,
                'rand_layout_full': True,
                'rand_shape_count': True,
                'rand_dynamics': True,
            }),
        ])

    # collection of ALL env specifications
    env_cls_suffix_kwargs = [
        *cluster_variants,
        *find_dupe_variants,
        *fix_colour_variants,
        *make_line_variants,
        *match_regions_variants,
        *move_to_corner_variants,
        *move_to_region_variants,
    ]

    # register all the envs and record their names
    # TODO: make registration lazy, so that I can do it automatically without
    # importing all the benchmark code (including Pyglet code, etc.).
    registered_env_names = []
    for env_class, env_ep_len, env_suffix, env_kwargs in env_cls_suffix_kwargs:
        base_env_name = env_class.make_name(env_suffix)
        registered_env_names.append(base_env_name)
        gym.register(base_env_name,
                     entry_point=env_class,
                     max_episode_steps=env_ep_len,
                     kwargs={
                         'max_episode_steps': env_ep_len,
                         **common_kwargs,
                         **env_kwargs,
                     })

        for preproc_str, constructor in \
                DEFAULT_PREPROC_ENTRY_POINT_WRAPPERS.items():
            new_name = env_class.make_name(env_suffix + f'-{preproc_str}')
            registered_env_names.append(new_name)
            gym.register(new_name,
                         entry_point=constructor(env_class),
                         max_episode_steps=env_ep_len,
                         kwargs={
                             'max_episode_steps': env_ep_len,
                             **common_kwargs,
                             **env_kwargs,
                         })

    train_to_test_map = {}
    observed_demo_envs = set()
    for name in registered_env_names:
        parsed = EnvName(name)
        if parsed.is_test:
            test_l = train_to_test_map.setdefault(parsed.demo_env_name, [])
            test_l.append(parsed.env_name)
        else:
            observed_demo_envs.add(parsed.env_name)

    # use immutable values
    train_to_test_map = {k: tuple(v) for k, v in train_to_test_map.items()}

    envs_with_test_variants = train_to_test_map.keys()
    assert observed_demo_envs == envs_with_test_variants, \
        "there are some train envs without test envs, or test envs without " \
        "train envs"
    sorted_items = sorted(train_to_test_map.items())
    DEMO_ENVS_TO_TEST_ENVS_MAP.update(sorted_items)

    # Debugging environment: MoveToCorner with a nicely shaped reward function
    # that you can simply do RL on.
    debug_mtc_kwargs = dict(max_episode_steps=mtc_ep_len,
                            kwargs={
                                'debug_reward': True,
                                'max_episode_steps': mtc_ep_len,
                                'rand_shape_colour': False,
                                'rand_shape_type': False,
                                'rand_shape_pose': False,
                                'rand_robot_pose': False,
                                **common_kwargs,
                            })
    debug_mtc_suffix = '-DebugReward'
    gym.register(MoveToCornerEnv.make_name(debug_mtc_suffix),
                 entry_point=MoveToCornerEnv,
                 **debug_mtc_kwargs)
    for preproc_str, constructor in \
            DEFAULT_PREPROC_ENTRY_POINT_WRAPPERS.items():
        gym.register(
            MoveToCornerEnv.make_name(f'{debug_mtc_suffix}-{preproc_str}'),
            entry_point=constructor(MoveToCornerEnv),
            **debug_mtc_kwargs)

    return True
