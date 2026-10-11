"""Bounded action distribution; no clipped out-of-range Gaussian proposals."""
import torch
from stable_baselines3 import PPO
from stable_baselines3.common.policies import ActorCriticPolicy
from stable_baselines3.common.distributions import SquashedDiagGaussianDistribution

class BoundedYawPolicy(ActorCriticPolicy):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.action_dist = SquashedDiagGaussianDistribution(1)
        self._squash_output = True

class AuditedPPO(PPO):
    def _excluded_save_params(self):
        return super()._excluded_save_params() + ["ledger", "_audit_hook", "audit_root"]

    def attach_audit(self, root, ledger):
        from pathlib import Path
        self.audit_root, self.ledger = Path(root), ledger
        self.optimizer_steps = 0
        def count(opt, args, kwargs):
            self.optimizer_steps += 1
            if not all(torch.isfinite(p).all() for p in self.policy.parameters()):
                raise RuntimeError("nonfinite_optimizer_parameter")
            self.ledger.event("optimizer_step", step=self.optimizer_steps, decisions=self.num_timesteps)
        self._audit_hook = self.policy.optimizer.register_step_post_hook(count)
    def train(self):
        super().train()
        values = {k:float(v) for k,v in self.logger.name_to_value.items() if k.startswith("train/")}
        if not all(torch.isfinite(torch.tensor(v)).item() for v in values.values()):
            raise RuntimeError("nonfinite_loss")
        self.ledger.event("ppo_update", decisions=self.num_timesteps,optimizer_steps=self.optimizer_steps,
                          epoch_updates=self._n_updates, metrics=values)
        self.save(self.audit_root / f"checkpoint-{self.num_timesteps}")
        print({"decisions":self.num_timesteps,"optimizer_steps":self.optimizer_steps,"metrics":values},flush=True)
