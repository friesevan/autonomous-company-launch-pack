# The no-Claude queue

Scripts in this folder run, in name order, whenever the usage governor says no Claude session may start (a limit was hit, or today's share is spent). `tools/run_queue.sh` runs each `*.sh` or `*.py` once, logs its output to `ops/runs/queue-<time>.log`, and moves it to `done/`. The next Claude session reads the logs.

Good queue items: a full build and test run through `tools/xc.sh`, Simulator screenshots, clearing DerivedData, regenerating the site, archiving old run logs. Name them so the order is obvious: `10-build-and-test.sh`, `20-screenshots.sh`.
