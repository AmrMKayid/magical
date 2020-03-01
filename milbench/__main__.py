"""Tool for demonstrating MILBench and collecting demos."""

import datetime
import gzip
import os
import sys
import time

import click
import cloudpickle
import gym
from imitation.util.rollout import TrajectoryAccumulator
from pyglet.window import key

from milbench.benchmarks import register_envs
from milbench.entities import RobotAction as RA


def get_unique_fn(env_name):
    now = datetime.datetime.now()
    time_str = now.strftime('%FT%k:%M:%S')
    return f"demo-{env_name}-{time_str}.pkl.gz"


@click.command()
@click.option("--record",
              type=str,
              default=None,
              help="directory to record demos to, if any")
@click.option("--env-name",
              default='MoveToCorner-Demo-LoResStack-v0',
              help='name of environment')
def main(record, env_name):
    if record:
        record_dir = os.path.abspath(record)
        print(f"Will record demos to '{record_dir}'")
        os.makedirs(record_dir, exist_ok=True)
        traj_accum = TrajectoryAccumulator()

    register_envs()
    env = gym.make(env_name)
    try:
        obs = env.reset()
        was_done_on_prev_step = False
        if record:
            traj_accum.add_step({"obs": obs})
            started = False
            print("Will only start recording on first key press")
        else:
            started = True

        # first render to open window
        env.render(mode='human')

        # keys that are depressed will end up in key_map
        key_map = key.KeyStateHandler()
        env.viewer.window.push_handlers(key_map)

        # render loop
        spf = 1.0 / env.fps
        while env.viewer.isopen:
            if key_map[key.R]:
                # drop traj and don't save
                obs = env.reset()
                if record:
                    started = False
                    traj_accum = TrajectoryAccumulator()
                    traj_accum.add_step({"obs": obs})
                else:
                    started = True
                was_done_on_prev_step = False

            # for limiting FPS
            frame_start = time.time()

            # movement and gripper keys
            act_flags = [RA.NONE, RA.NONE, RA.OPEN]
            if key_map[key.UP] and not key_map[key.DOWN]:
                act_flags[0] = RA.UP
            elif key_map[key.DOWN] and not key_map[key.UP]:
                act_flags[0] = RA.DOWN
            if key_map[key.LEFT] and not key_map[key.RIGHT]:
                act_flags[1] = RA.LEFT
            elif key_map[key.RIGHT] and not key_map[key.LEFT]:
                act_flags[1] = RA.RIGHT
            if key_map[key.SPACE]:
                # close gripper (otherwise it's open)
                act_flags[2] = RA.CLOSE
            # "flat" integer action
            action = env.flags_to_action(act_flags)
            was_started = started
            started = started or action != 0
            if started and not was_started:
                print("Detected non-null action, starting recording")

            if started:
                obs, rew, done, info = env.step(action)

                if done and not was_done_on_prev_step:
                    print(f"Done, score {info['eval_score']:.4g}/1.0")

                if record:
                    traj_accum.add_step({
                        "rews": rew,
                        "obs": obs,
                        "acts": action,
                        "infos": info,
                    })
                    if done and not was_done_on_prev_step:
                        traj = traj_accum.finish_trajectory()
                        new_path = os.path.join(record_dir,
                                                get_unique_fn(env_name))
                        pickle_data = {
                            'env_name': env_name,
                            'trajectory': traj,
                            'score': info['eval_score'],
                        }
                        print(
                            f"Saving trajectory ({len(traj.obs)} obs, "
                            f"{len(traj.acts)} actions, {len(traj.rews)} rews) "
                            f"to '{new_path}'")
                        with gzip.GzipFile(new_path, 'wb') as fp:
                            cloudpickle.dump(pickle_data, fp)

                # for things we only want to run the FIRST time the env gives is a
                # 'done' flag
                was_done_on_prev_step = done

            # render to screen
            env.render(mode='human')

            # wait for next frame
            elapsed = time.time() - frame_start
            if elapsed < spf:
                time.sleep(spf - elapsed)
    finally:
        # once done, close the window
        env.close()


if __name__ == '__main__':
    try:
        with main.make_context(sys.argv[0], sys.argv[1:]) as ctx:
            result = main.invoke(ctx)
    except click.ClickException as e:
        e.show()
        sys.exit(e.exit_code)
    except click.exceptions.Exit as e:
        sys.exit(e.exit_code)
