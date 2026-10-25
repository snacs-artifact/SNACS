import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Step_4_Student"))

MAX_ITERS = 8


def build(args):
    sdg_path, cache_path = args
    if os.path.exists(cache_path):
        return "skip", None
    try:
        import torch
        from teacher_taint_engine import SDGTaintEngine

        from utils.ablation import filter_sdg_edges

        with open(sdg_path, "r") as f:
            graph_json = json.load(f)
        # Table VIII arms: the teacher must not propagate over a relation the
        # student cannot see. No-op unless DROP_RELATIONS is set.
        graph_json = filter_sdg_edges(graph_json)
        out = SDGTaintEngine(graph_json).run(max_iters=MAX_ITERS)
        tmp = cache_path + ".tmp%d" % os.getpid()
        torch.save(out, tmp)
        os.replace(tmp, cache_path)  # atomic: never a half-written cache entry
        return "ok", None
    except Exception as e:
        return "fail", f"{os.path.basename(sdg_path)}: {e!r}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sdg_folder", required=True)
    ap.add_argument("--cache_dir", required=True)
    ap.add_argument("--workers", type=int, default=int(os.environ.get("WORKERS", 32)))
    a = ap.parse_args()

    from utils.ablation import assert_teacher_cache_matches, describe

    os.makedirs(a.cache_dir, exist_ok=True)
    assert_teacher_cache_matches(a.cache_dir)
    names = sorted(f[:-5] for f in os.listdir(a.sdg_folder) if f.endswith(".json"))
    jobs = [(os.path.join(a.sdg_folder, n + ".json"),
             os.path.join(a.cache_dir, n + ".pt")) for n in names]

    print(f"{len(jobs)} graphs | sd_weight={os.environ.get('SD_EDGE_WEIGHT', '0.9 (default)')} "
          f"| {describe()} | workers={a.workers} -> {a.cache_dir}", flush=True)

    counts = {"ok": 0, "skip": 0, "fail": 0}
    errs = []
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(build, j) for j in jobs]
        for i, fut in enumerate(as_completed(futs), 1):
            status, err = fut.result()
            counts[status] += 1
            if err:
                errs.append(err)
            if i % 250 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)}  {counts}", flush=True)

    print(f"DONE {counts}")
    if errs:
        print("errors:", errs[:10])
        sys.exit(1)


if __name__ == "__main__":
    main()

