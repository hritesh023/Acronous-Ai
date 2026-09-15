"""Acronous LLM self-training loop — Contabo VPS brain.

Resource-safe by design for Contabo Cloud VPS 8 (24GB RAM / 300GB disk,
167.86.104.155). The trainer NEVER fills the box:

  RAM guard  — every cycle checks system memory; if use is above
    ACRONOUS_SELF_TRAIN_MAX_RAM_PCT (default 85%) the cycle SKIPPs and
    retries later. Batches are small (default 400 pairs/cycle) and all
    collection is streaming — no full-corpus in-memory loads, no O(n^2).

  Disk guard — training dir quota ACRONOUS_SELF_TRAIN_MAX_TRAIN_GB
    (default 25GB on a 300GB disk) + data-disk free floor
    ACRONOUS_SELF_TRAIN_MIN_FREE_GB (set 40 on the VPS). Merged dataset
    capped at ACRONOUS_SELF_TRAIN_MAX_MERGED_PAIRS (default 20000 pairs,
    ~100MB JSONL). Snapshots pruned to newest N + younger than M days;
    eval reports pruned the same way.

Intelligence still compounds daily because Tier 1 (RAG + SQLite memory +
knowledge graph + per-turn learning) runs continuously and is itself
bounded (confidence decay, stale pruning, capped entries) — see
internet_learner.py / memory.py. Tier 2 distills the freshest facts into
small daily JSONL; Tier 3 LoRA only runs on GPU hosts with headroom.

Env:
  ACRONOUS_SELF_TRAIN=true|false
  ACRONOUS_SELF_TRAIN_INTERVAL=21600
  ACRONOUS_SELF_TRAIN_MIN_FACTS=500
  ACRONOUS_SELF_TRAIN_MAX_RAM_PCT=85
  ACRONOUS_SELF_TRAIN_MIN_FREE_GB=10      (VPS prod: 40)
  ACRONOUS_SELF_TRAIN_MAX_TRAIN_GB=25
  ACRONOUS_SELF_TRAIN_MAX_PAIRS_PER_CYCLE=400
  ACRONOUS_SELF_TRAIN_MAX_MERGED_PAIRS=20000
  ACRONOUS_SELF_TRAIN_RETAIN_DAYS=14
  ACRONOUS_SELF_TRAIN_RETAIN_SNAPSHOTS=7
  ACRONOUS_TRAIN_GPU=auto
"""
import json
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

IDENTITY_SYSTEM = (
    "You are Acronous AI — a friendly, conversational AI assistant created by Acronous. "
    "Be warm, natural, and human-like. Never reveal model/provider/backend details."
)


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def _ram_snapshot():
    """Return (used_pct, avail_mb). Zero-dependency: psutil if present,
    else /proc/meminfo on Linux, else (0.0, -1) = unknown/OK on dev."""
    try:
        import psutil  # optional
        vm = psutil.virtual_memory()
        return float(vm.percent), float(vm.available) / (1024 * 1024)
    except ImportError:
        pass
    except Exception:
        pass
    try:
        if os.path.exists("/proc/meminfo"):
            info = {}
            with open("/proc/meminfo", encoding="utf-8") as fh:
                for line in fh:
                    parts = line.split()
                    if len(parts) >= 2 and parts[0].endswith(":"):
                        try:
                            info[parts[0][:-1]] = int(parts[1])  # kB
                        except ValueError:
                            pass
            total = info.get("MemTotal", 0)
            avail = info.get("MemAvailable", info.get("MemFree", 0))
            if total > 0:
                used_pct = (total - avail) / total * 100.0
                return used_pct, avail / 1024.0
    except Exception:
        pass
    return 0.0, -1.0  # unknown → treat as OK (dev machines)


def _disk_free_gb(path):
    try:
        usage = shutil.disk_usage(str(path))
        return usage.free / (1024 ** 3), usage.total / (1024 ** 3)
    except Exception:
        return -1.0, -1.0


def _dir_size_gb(path):
    total = 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
    except FileNotFoundError:
        return 0.0
    except OSError:
        return 0.0
    return total / (1024 ** 3)


class SelfTrainer:
    """Distills brain knowledge into bounded instruction datasets + opportunistic LoRA."""

    def __init__(self, config, memory=None, rag=None, internet_learner=None, llm=None):
        self.config = config
        self.memory = memory
        self.rag = rag
        self.internet_learner = internet_learner
        self.llm = llm
        data_dir = Path(getattr(config, "DATA_DIR", "data"))
        train_name = getattr(config, "TRAINING_DIR_NAME", "training")
        self.training_dir = data_dir / train_name
        self.training_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.training_dir / "self_train_state.json"
        self.state = self._load_state()

    # ── caps ───────────────────────────────────────────────────────────
    def _caps(self):
        c = self.config
        return {
            "max_ram_pct": float(getattr(c, "SELF_TRAIN_MAX_RAM_PCT", 85)),
            "min_free_gb": float(getattr(c, "SELF_TRAIN_MIN_FREE_GB", 10)),
            "max_train_gb": float(getattr(c, "SELF_TRAIN_MAX_TRAIN_GB", 25)),
            "max_pairs_cycle": int(getattr(c, "SELF_TRAIN_MAX_PAIRS_PER_CYCLE", 400)),
            "max_merged": int(getattr(c, "SELF_TRAIN_MAX_MERGED_PAIRS", 20000)),
            "retain_days": int(getattr(c, "SELF_TRAIN_RETAIN_DAYS", 14)),
            "retain_snaps": int(getattr(c, "SELF_TRAIN_RETAIN_SNAPSHOTS", 7)),
        }

    def resource_snapshot(self):
        caps = self._caps()
        ram_pct, ram_avail_mb = _ram_snapshot()
        free_gb, total_gb = _disk_free_gb(self.training_dir)
        train_gb = _dir_size_gb(self.training_dir)
        return {"ram_used_pct": round(ram_pct, 1), "ram_avail_mb": round(ram_avail_mb, 1),
                "disk_free_gb": round(free_gb, 2), "disk_total_gb": round(total_gb, 2),
                "training_dir_gb": round(train_gb, 3), "caps": caps}

    def check_resources(self, for_lora=False):
        """True/False gate + reason. Called before dataset build AND LoRA."""
        caps = self._caps()
        snap = self.resource_snapshot()
        if snap["ram_used_pct"] and snap["ram_used_pct"] >= caps["max_ram_pct"]:
            return False, f"ram {snap['ram_used_pct']}% >= cap {caps['max_ram_pct']}%", snap
        if snap["disk_free_gb"] >= 0 and snap["disk_free_gb"] < caps["min_free_gb"]:
            return False, f"disk free {snap['disk_free_gb']}GB < floor {caps['min_free_gb']}GB", snap
        if snap["training_dir_gb"] >= caps["max_train_gb"]:
            # try a prune first; re-measure once
            self.prune_old_artifacts()
            snap = self.resource_snapshot()
            if snap["training_dir_gb"] >= caps["max_train_gb"]:
                return False, (f"training dir {snap['training_dir_gb']}GB >= quota "
                               f"{caps['max_train_gb']}GB even after prune"), snap
        if for_lora and snap["ram_used_pct"] and snap["ram_used_pct"] >= 70.0:
            return False, f"ram {snap['ram_used_pct']}% too high for LoRA (needs <70%)", snap
        return True, "ok", snap

    # ── state ──────────────────────────────────────────────────────────
    def _load_state(self):
        try:
            if self.state_path.exists():
                return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {"last_cycle": None, "last_lora": None, "cycles": 0,
                "total_pairs": 0, "last_eval": None, "mode": "dataset-only",
                "skipped": 0}

    def _save_state(self):
        try:
            self.state_path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("[SELF-TRAIN] state save failed: %s", exc)

    # ── dataset (streaming, bounded) ───────────────────────────────────
    def _collect_facts(self, limit=400):
        """Stream facts with O(1) extra memory per item (set-based dedup)."""
        limit = max(1, min(int(limit), 2000))
        seen = set()
        count = 0

        def _emit(text, source, confidence):
            nonlocal count
            if not text or len(text) < 20 or count >= limit:
                return None
            key = text[:120].lower()
            if key in seen:
                return None
            seen.add(key)
            count += 1
            return {"text": text[:800], "source": source, "confidence": confidence}

        # 1. fresh SQLite knowledge (internet learner output) — newest first
        try:
            if self.memory and hasattr(self.memory, "get_fresh_knowledge"):
                rows = self.memory.get_fresh_knowledge(hours=24 * 30, limit=limit) or []
                for f in rows:
                    if count >= limit:
                        break
                    text = (f.get("fact") or f.get("value") or f.get("text") or "").strip()
                    fact = _emit(text, f.get("source", "memory"), f.get("confidence", 0.5))
                    if fact:
                        yield fact
        except Exception as exc:
            logger.debug("[SELF-TRAIN] memory collect failed: %s", exc)
        # 2. RAG documents — tail only, set dedup (no O(n^2) scans)
        try:
            docs = getattr(self.rag, "documents", []) or []
            for d in reversed(docs[-limit:]):
                if count >= limit:
                    break
                t = (d.get("text") or "").strip()
                if len(t) < 30:
                    continue
                fact = _emit(t, "rag", 0.5)
                if fact:
                    yield fact
        except Exception:
            pass
        # 3. knowledge-graph concepts — small fixed addition
        try:
            kg = getattr(self.internet_learner, "knowledge_graph", None)
            if kg:
                for name, _ in kg.get_important_concepts(top_k=50):
                    if count >= limit or not name or len(name) <= 2:
                        continue
                    fact = _emit(f"Key concept: {name}. Explain it accurately and concisely.",
                                 "kg", 0.4)
                    if fact:
                        yield fact
        except Exception:
            pass

    @staticmethod
    def _fact_to_pair(fact):
        """Turn a learned fact into an instruction-tuning pair.

        Keeps Acronous identity fixed so fine-tunes never leak Qwen/Ollama
        provider names into first-person answers.
        """
        text = fact["text"]
        if text.startswith("Q:"):
            parts = text.split("\nA:", 1)
            instruction = parts[0].replace("Q:", "").strip()[:400] or "Explain this fact clearly."
            output = parts[1].strip()[:1200] if len(parts) > 1 else text[:1200]
        elif text.startswith("Key concept:"):
            instruction = f"{text} Give a helpful 3-5 sentence explanation."
            output = ("As Acronous AI, here is a concise, accurate explanation "
                      f"based on my learned knowledge: {text[:600]}")
        else:
            instruction = ("Using your learned knowledge, answer accurately and concisely. "
                           f"Fact context: {text[:500]}")
            output = text[:1200]
        return {"instruction": instruction,
                "input": "",
                "output": output,
                "system": IDENTITY_SYSTEM,
                "meta": {"source": fact.get("source", "?"),
                         "confidence": fact.get("confidence", 0.5),
                         "created": _utcnow_iso()}}

    def build_dataset(self, limit=None):
        caps = self._caps()
        if limit is None:
            limit = caps["max_pairs_cycle"]
        limit = max(1, min(int(limit), caps["max_pairs_cycle"]))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out = self.training_dir / f"acronous-instruct-{stamp}.jsonl"
        merged = self.training_dir / "acronous-instruct-merged.jsonl"
        n = 0
        with open(out, "w", encoding="utf-8") as fh:
            for fact in self._collect_facts(limit=limit):
                fh.write(json.dumps(self._fact_to_pair(fact), ensure_ascii=False) + "\n")
                n += 1
        # append then enforce merged cap (keep most recent N lines)
        if n:
            with open(out, encoding="utf-8") as src, open(merged, "a", encoding="utf-8") as dst:
                shutil.copyfileobj(src, dst)
        self._enforce_merged_cap(caps["max_merged"])
        self.prune_old_artifacts()
        self.state["total_pairs"] = self.state.get("total_pairs", 0) + n
        logger.info("[SELF-TRAIN] dataset %s — %d pairs (%d lifetime, merged cap %d)",
                    out.name, n, self.state["total_pairs"], caps["max_merged"])
        return {"file": str(out), "pairs": n, "total_pairs": self.state["total_pairs"],
                "resources": self.resource_snapshot()}

    def _enforce_merged_cap(self, max_lines):
        """Keep only the newest max_lines of the merged file (bounded disk)."""
        merged = self.training_dir / "acronous-instruct-merged.jsonl"
        if not merged.exists() or max_lines <= 0:
            return
        try:
            # cheap line count without loading the file
            with open(merged, "rb") as fh:
                count = sum(1 for _ in fh)
            if count <= max_lines:
                return
            tmp = merged.with_suffix(".tmp")
            with open(merged, "rb") as fh:
                # seek from tail: read all lines but keep only tail (lines are short;
                # worst case ~20000 * ~2KB = ~40MB transient — well within budget)
                lines = fh.readlines()[-max_lines:]
            with open(tmp, "wb") as fh:
                fh.writelines(lines)
            os.replace(tmp, merged)
            logger.info("[SELF-TRAIN] merged trimmed %d -> %d lines (disk cap)", count, max_lines)
        except Exception as exc:
            logger.warning("[SELF-TRAIN] merged trim failed: %s", exc)

    def prune_old_artifacts(self):
        """Delete old snapshots/evals beyond retain policy. Merged file is capped, never deleted."""
        caps = self._caps()
        now = time.time()
        try:
            snaps = sorted(self.training_dir.glob("acronous-instruct-2*.jsonl"),
                           key=lambda p: p.stat().st_mtime, reverse=True)
            for old in snaps[caps["retain_snaps"]:]:
                try:
                    old.unlink()
                except OSError:
                    pass
            for p in list(snaps[:caps["retain_snaps"]]):
                try:
                    if now - p.stat().st_mtime > caps["retain_days"] * 86400:
                        p.unlink()
                except OSError:
                    pass
            evals = sorted(self.training_dir.glob("eval-*.json"),
                           key=lambda p: p.stat().st_mtime, reverse=True)
            for old in evals[caps["retain_snaps"]:]:
                try:
                    old.unlink()
                except OSError:
                    pass
        except Exception as exc:
            logger.debug("[SELF-TRAIN] prune failed: %s", exc)

    # ── LoRA (opportunistic, guarded) ──────────────────────────────────
    def _gpu_available(self):
        mode = os.getenv("ACRONOUS_TRAIN_GPU", "auto").lower()
        if mode == "force-cpu":
            return False
        if mode == "force-gpu":
            return True
        try:
            import torch
            return bool(torch.cuda.is_available())
        except ImportError:
            return False

    def _merged_size(self):
        try:
            merged = self.training_dir / "acronous-instruct-merged.jsonl"
            if not merged.exists():
                return 0
            with open(merged, "rb") as fh:
                return sum(1 for _ in fh)
        except Exception:
            return 0

    def try_lora_train(self):
        """Attempt QLoRA only with GPU + headroom + eval pass.

        CPU-only VPS (normal case): returns deferred with the exact GPU
        command — never blocks, never OOMs the brain.
        """
        ok, reason, snap = self.check_resources(for_lora=True)
        if not ok:
            return {"status": "skip", "reason": f"resources: {reason}", "resources": snap}
        min_facts = int(getattr(self.config, "SELF_TRAIN_MIN_FACTS", 500))
        merged_n = self._merged_size()
        if merged_n < min_facts:
            return {"status": "skip", "reason": f"need {min_facts} pairs, have {merged_n}"}
        if not self._gpu_available():
            cmd = ("python -m acronous_llm.train_lora "
                   "--base Qwen/Qwen3-8B --data data/training/acronous-instruct-merged.jsonl "
                   "--out data/models/acronous-brain-lora --quant 4bit")
            logger.info("[SELF-TRAIN] CPU-only host — LoRA deferred. GPU run: %s", cmd)
            return {"status": "deferred-cpu", "pairs": merged_n, "gpu_command": cmd,
                    "resources": snap}
        try:
            from acronous_llm.train_lora import run_lora  # GPU hosts only
            out = run_lora(str(self.training_dir / "acronous-instruct-merged.jsonl"))
            self.state["last_lora"] = _utcnow_iso()
            self._save_state()
            return {"status": "ok", "adapter": out, "resources": snap}
        except Exception as exc:
            logger.warning("[SELF-TRAIN] LoRA failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    # ── eval (gated promotion, streaming) ──────────────────────────────
    def evaluate(self, sample_n=20):
        """Lightweight eval over a streaming sample of merged (no full load)."""
        merged = self.training_dir / "acronous-instruct-merged.jsonl"
        sample = []
        try:
            if merged.exists():
                with open(merged, encoding="utf-8") as fh:
                    for i, line in enumerate(fh):
                        if len(sample) >= sample_n:
                            # reservoir-ish: keep it simple, take evenly spaced tail
                            break
                        if i >= max(0, self._merged_size() - sample_n * 10):
                            try:
                                sample.append(json.loads(line))
                            except Exception:
                                pass
        except Exception:
            pass
        passed, total = 0, max(1, len(sample))
        failures = []
        for r in sample:
            out = (r.get("output") or "")
            leak = any(k in out for k in ["I am Qwen", "I am GPT", "I am Claude", "as an AI language model"])
            if not leak and len(out) > 20:
                passed += 1
            else:
                failures.append((r.get("instruction", "")[:60], out[:60]))
        score = passed / total
        report = {"score": round(score, 3), "passed": passed, "total": total,
                  "gate": "pass" if score >= 0.9 else "fail",
                  "failures": failures[:5], "at": _utcnow_iso()}
        rep_path = self.training_dir / f"eval-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
        try:
            rep_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        except Exception:
            pass
        self.prune_old_artifacts()
        self.state["last_eval"] = report
        self._save_state()
        logger.info("[SELF-TRAIN] eval %s (%d/%d)", report["gate"], passed, total)
        return report

    # ── scheduled cycle ────────────────────────────────────────────────
    def should_run_cycle(self):
        if not bool(getattr(self.config, "SELF_TRAIN_ENABLED", True)):
            return False
        interval = int(getattr(self.config, "SELF_TRAIN_INTERVAL", 21600))
        last = self.state.get("last_cycle")
        if not last:
            return True
        try:
            last_ts = datetime.fromisoformat(last).timestamp()
            return (time.time() - last_ts) >= interval
        except Exception:
            return True

    def run_cycle(self, limit=None):
        """One bounded self-train cycle: guard → dataset → eval → LoRA.

        Never throws for resource skips — returns a skipped result so the
        scheduler simply retries next interval.
        """
        ok, reason, snap = self.check_resources()
        if not ok:
            self.state["skipped"] = int(self.state.get("skipped", 0)) + 1
            self._save_state()
            logger.info("[SELF-TRAIN] cycle skipped (%s)", reason)
            return {"at": _utcnow_iso(), "status": "skipped", "reason": reason,
                    "resources": snap}
        result = {"at": _utcnow_iso(), "status": "ok", "resources": snap}
        result["dataset"] = self.build_dataset(limit=limit)
        result["eval"] = self.evaluate()
        if result["eval"].get("gate") == "pass":
            result["lora"] = self.try_lora_train()
        else:
            result["lora"] = {"status": "skip", "reason": "eval gate failed"}
        self.state["last_cycle"] = _utcnow_iso()
        self.state["cycles"] = int(self.state.get("cycles", 0)) + 1
        self.state["mode"] = result["lora"].get("status", "dataset-only")
        self.state["resources"] = self.resource_snapshot()
        self._save_state()
        return result

    def get_status(self):
        return {"enabled": bool(getattr(self.config, "SELF_TRAIN_ENABLED", True)),
                "interval_s": int(getattr(self.config, "SELF_TRAIN_INTERVAL", 21600)),
                "min_facts": int(getattr(self.config, "SELF_TRAIN_MIN_FACTS", 500)),
                "merged_pairs": self._merged_size(),
                "total_pairs": self.state.get("total_pairs", 0),
                "cycles": self.state.get("cycles", 0),
                "skipped": self.state.get("skipped", 0),
                "last_cycle": self.state.get("last_cycle"),
                "last_lora": self.state.get("last_lora"),
                "last_eval": self.state.get("last_eval"),
                "gpu": self._gpu_available(),
                "resources": self.resource_snapshot(),
                "brain": {"host": getattr(self.config, "BRAIN_HOST", "brain.acronous.com"),
                          "direct": getattr(self.config, "BRAIN_DIRECT_URL",
                                            "http://167.86.104.155:11434"),
                          "chat_model": getattr(self.config, "LLM_CHAT_MODEL", "qwen3:8b")}}
