from typing import Optional

import torch

from diagnnose.typedefs.activations import ActivationTensors
from diagnnose.typedefs.models import SizeDict
from diagnnose.utils.pickle import load_pickle


class InitStates:
    """Initial lstm states that are passed to LM at start of sequence.

    Attributes
    ----------
    sizes : SizeDict
        Language model for which init states will be created.
    init_states_path : str, optional
        Path to pickled file with initial lstm states. If not provided
        zero-valued init states will be created.
    """

    def __init__(
        self, sizes: SizeDict, init_states_path: Optional[str] = None
    ) -> None:
        self.sizes = sizes
        self.num_layers = len(sizes)

        self.init_states_path = init_states_path

    def create(self, batch_size: int = 1) -> ActivationTensors:
        """ Set up the initial LM states.

        If no path is provided 0-initialized embeddings will be used.
        Note that the loaded init should provide tensors for `hx`
        and `cx` in all layers of the LM.

        Arguments
        ---------
        batch_size : int, optional
            Number of batch items, towards which the initial states
            will be expanded. Defaults to 1.

        Returns
        -------
        init_states : TensorDict
            TensorDict containing the initial states for each layer.
        """
        if self.init_states_path is not None:
            init_states: ActivationTensors = load_pickle(self.init_states_path)

            self._validate(init_states)

            init_states = self._expand_batch_size(init_states, batch_size)

            return init_states

        return self.create_zero_state(batch_size)

    def create_zero_state(self, batch_size: int = 1) -> ActivationTensors:
        """Zero-initialized states if no init state is provided."""
        init_states: ActivationTensors = {}

        for layer in range(self.num_layers):
            init_states[layer, "cx"] = self._create_zero_state(
                self.sizes[layer]["c"], batch_size
            )
            init_states[layer, "hx"] = self._create_zero_state(
                self.sizes[layer]["c"], batch_size
            )

        return init_states

    def _validate(self, init_states: ActivationTensors) -> None:
        """ Performs a simple validation of the new initial states.

        Parameters
        ----------
        init_states: TensorDict
            New initial states that should have a structure that
            complies with the dimensions of the language model.
        """
        assert (
            len(init_states) == self.num_layers
        ), "Number of initial layers not correct"
        for layer, layer_size in self.sizes.items():
            assert (layer, "hx") in init_states.keys() and (
                layer,
                "cx",
            ) in init_states.keys(), (
                "Initial layer names not correct, should be hx and cx"
            )

            assert init_states[layer, "hx"].size(0) == self.sizes[layer]["h"], (
                "Initial activation size for hx is incorrect: "
                f'hx: {init_states[layer, "hx"].size(0)}, should be {self.sizes[layer]["h"]}'
            )

            assert init_states[layer, "cx"].size(0) == self.sizes[layer]["c"], (
                "Initial activation size for cx is incorrect: "
                f'cx: {init_states[layer, "cx"].size(0)}, should be {self.sizes[layer]["c"]}'
            )

    def _expand_batch_size(
        self, init_states: ActivationTensors, batch_size: int
    ) -> ActivationTensors:
        """Expands the init_states in the batch dimension."""
        batch_init_states: ActivationTensors = {}

        for layer in range(self.num_layers):
            batch_init_states[layer, "cx"] = torch.repeat_interleave(
                init_states[layer, "cx"].unsqueeze(0), batch_size, dim=0
            )
            batch_init_states[layer, "hx"] = torch.repeat_interleave(
                init_states[layer, "hx"].unsqueeze(0), batch_size, dim=0
            )

        return batch_init_states

    @staticmethod
    def _create_zero_state(size: int, batch_size: int) -> torch.Tensor:
        return torch.zeros((batch_size, size))
