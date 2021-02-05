# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from maro.rl import ActorClient, AbortRollout
from maro.utils import LogFormat, Logger


class SimpleActorClient(ActorClient):
    def __init__(
        self, env, agent_proxy, state_shaper, action_shaper, experience_shaper,
        receive_action_timeout=None, max_receive_action_attempts=None
    ):
        super().__init__(
            env, agent_proxy, 
            state_shaper=state_shaper, action_shaper=action_shaper, experience_shaper=experience_shaper,
            receive_action_timeout=receive_action_timeout, max_receive_action_attempts=max_receive_action_attempts
        )
        self._logger = Logger("actor_client", format_=LogFormat.simple, auto_timestamp=False)
    
    def roll_out(self, index, training=True):
        self.env.reset()
        time_step = 0
        metrics, event, is_done = self.env.step(None)
        while not is_done:
            state = self.state_shaper(event, self.env.snapshot_list)
            agent_id = str(event.port_idx)
            action = self.get_action(state, index, time_step, agent_id=agent_id)
            if isinstance(action, AbortRollout):
                return None, None

            time_step += 1
            if action is None:
                metrics, event, is_done = self.env.step(None)
                self._logger.info(f"Failed to receive an action for time step {time_step}, proceed with no action.")
            else:
                self.experience_shaper.record(
                    {"state": state, "agent_id": agent_id, "event": event, "action": action}
                )
                metrics, event, is_done = self.env.step(self.action_shaper(action, event, self.env.snapshot_list))
                
        exp = self.experience_shaper(self.env.snapshot_list) if training else None
        self.experience_shaper.reset()

        return self.env.metrics, exp
