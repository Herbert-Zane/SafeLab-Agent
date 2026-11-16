#!/usr/bin/env bash
# S6 evaluator-coverage check on the server, detached. No API key: scripted backend only.
# usage (on the server): bash ~/zcy/s6_evalcov_p36914f5/run_s6.sh
# Layout: ~/zcy/s6_evalcov_p36914f5/{sequences,runs,server}; the platform checkout
# ~/zcy/bench_p36914f5 is the working directory of main.py and is only read.
# Two runs at a time; log server/s6.log, end marker server/s6.done.
D="$HOME/zcy/s6_evalcov_p36914f5"
B="$HOME/zcy/bench_p36914f5"
[ -e "$D/server/s6.log" ] && { echo "exists: $D/server/s6.log"; exit 1; }
mkdir -p "$D/runs" "$D/server"
export D B
setsid nohup bash -c '
  source "$HOME/miniconda3/etc/profile.d/conda.sh"
  conda activate isaaclab3
  export OMNI_KIT_ACCEPT_EULA=YES PYTHONIOENCODING=utf-8
  cd "$B" || exit 1
  one() {
    n=$1
    echo "### $(date +%F\ %T) start $n" >> "$D/server/s6.log"
    timeout 5400 python main.py --config configs/tasks/cell_lysis.json \
      --agent "$D/sequences/$n.json" \
      --agent-brief "$B/configs/agent_briefs/cell_lysis_normal_execution_v1.open.json" \
      --headless --output "$D/runs/$n" > "$D/runs/$n.log" 2>&1
    echo "### $(date +%F\ %T) end $n exit $?" >> "$D/server/s6.log"
    find "$D/runs/$n" \( -name "*.usda" -o -name "*.f32" -o -name kit.log \) -delete
  }
  one ctrl_fresh_tips & one p1_dirty_p200_into_ethanol & wait
  one p2_clean_return_to_ethanol & one p3_lysate_back_into_ethanol & wait
  echo "### $(date +%F\ %T) all done; platform status: $(git -C "$B" status --short | wc -l) changed paths" >> "$D/server/s6.log"
  touch "$D/server/s6.done"
' < /dev/null > /dev/null 2>&1 &
echo "started s6"
