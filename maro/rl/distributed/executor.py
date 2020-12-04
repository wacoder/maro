# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from maro.communication import Proxy, SessionMessage
from maro.rl.shaping.action_shaper import ActionShaper
from maro.rl.shaping.experience_shaper import ExperienceShaper
from maro.rl.shaping.state_shaper import StateShaper
from maro.rl.storage.column_based_store import ColumnBasedStore


class Executor(object):
    """An ``Executor`` is responsible for interacting with an environment.

    An ``Executor`` consists of a state shaper for observing the environment and an action shaper for executing
    actions on it. It also has an experience shaper that processes trajectories into experiences for remote training.

    Args:
        state_shaper (StateShaper, optional): It is responsible for converting the environment observation to model
            input.
        action_shaper (ActionShaper, optional): It is responsible for converting an agent's model output to environment
            executable action. Cannot be None under Inference and TrainInference modes.
        experience_shaper (ExperienceShaper, optional): It is responsible for processing data in the replay buffer at
            the end of an episode.
    """
    def __init__(
        self,
        state_shaper: StateShaper,
        action_shaper: ActionShaper,
        experience_shaper: ExperienceShaper,
        distributed_mode: DistributedTrainingMode
    ):
        self._state_shaper = state_shaper
        self._action_shaper = action_shaper
        self._experience_shaper = experience_shaper
        self._distributed_mode = distributed_mode
        if self._distributed_mode == DistributedTrainingMode.LEARNER_ACTOR:
            from maro.rl.distributed.learner_actor.common import Component, MessageTag, PayloadKey
            self._action_source = Component.LEARNER.value
        else:
            from maro.rl.distributed.actor_trainer.common import Component, MessageTag, PayloadKey
            self._action_source = Component.TRAINER.value

        self._message_tag_set = MessageTag
        self._payload_key_set = PayloadKey
        # Data structures to temporarily store transitions and trajectory
        self._transition_cache = {}
        self._trajectory = ColumnBasedStore()

        self._proxy = None

    def load_proxy(self, proxy: Proxy):
        self._proxy = proxy

    def choose_action(self, decision_event, snapshot_list):
        assert self._proxy is not None, "A proxy needs to be loaded first by calling load_proxy()"
        agent_id, model_state = self._state_shaper(decision_event, snapshot_list)
        payload = {self._payload_key_set.STATE: model_state, self._payload_key_set.AGENT_ID: agent_id}
        if self._distributed_mode == DistributedTrainingMode.ACTOR_TRAINER:
            payload[self._payload_key_set.ACTOR_ID] = self._proxy.component_name
        reply = self._proxy.send(
            SessionMessage(
                tag=self._message_tag_set.CHOOSE_ACTION,
                source=self._proxy.component_name,
                destination=self._action_source,
                payload=payload
            )
        )
        model_action = reply[0].payload[self._payload_key_set.ACTION]
        self._transition_cache = {
            "state": model_state,
            "action": model_action,
            "reward": None,
            "agent_id": agent_id,
            "event": decision_event
        }

        return self._action_shaper(model_action, decision_event, snapshot_list)

    def on_env_feedback(self, metrics):
        self._transition_cache["metrics"] = metrics
        self._trajectory.put(self._transition_cache)

    def post_process(self, snapshot_list):
        """Process the latest trajectory into experiences."""
        experiences = self._experience_shaper(self._trajectory, snapshot_list)
        self._trajectory.clear()
        self._transition_cache = {}
        self._state_shaper.reset()
        self._action_shaper.reset()
        self._experience_shaper.reset()
        return experiences
