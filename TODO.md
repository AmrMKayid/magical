# General code cleanup tasks I want to do at some point

- Abstract all of the environment interaction code to use a common main loop
  class which can handle keyboard I/O (if desired), resetting, saving
  demonstrations, recording videos, etc. This should be useful for all the
  baselines.
- Refactor the viewer so that it can do a separate render at a higher resolution
  for the human. This would be very useful for demonstrating the code, so that
  people don't have to squint at a 256x256 window on my laptop. I could
  additionally the default machine-readable image resolution to 512x512 or
  something else that seems reasonable (probably the arena is too small right
  now for the more advanced things I want to do). It would also be nice to have
  an interface for collecting demos that includes a counter for time remaining,
  a scoring interface, and some on-screen description of the task.
- Refactor state preprocessors so that demos aren't tied to a particular
  preprocessing of the environment.
- Move the test() and testall() functions in bc.py into their own rollout script
  in the baselines directory. Those two things shouldn't be immutably attached
  to BC.
- Fix bug in `dagger.py` (or maybe `DAggerTrainer` in imitation) that is causing
  it not to reload policies correctly. When I do `collect()`, it just seems to
  roll out randomly, which is not at all what I want. Can I verify that it's
  loading all of the correct weights? `save_policy()` and `reconstruct_policy()`
  seem to work, so it's evidently just something up with
  `reconstruct_trainer()` and/or `save_trainer()`.
- In Cluster* environments, consider changing the random layout function to
  avoid placing blocks of similar colour or type too close to one another (e.g.
  within ~4 shape radii). That should minimise the number of accidental clusters
  that the algorithm builds, at the cost of making placement expensive when
  there are many shapes.
