import netsquid.components.instructions as instr
from netsquid.components.qprocessor import QuantumProcessor
from netsquid.components.qprocessor import PhysicalInstruction
from netsquid.components.models import DephaseNoiseModel, DepolarNoiseModel

def create_processor(depolar_rate, dephase_rate):
    """Factory to create a quantum processor for each end node.

    Has two memory positions and the physical instructions necessary
    for teleportation.

    Parameters
    ----------
    depolar_rate : float
        Depolarization rate of qubits in memory.
    dephase_rate : float
        Dephasing rate of physical measurement instruction.

    Returns
    -------
    :class:`~netsquid.components.qprocessor.QuantumProcessor`
        A quantum processor to specification.

    """
    # We'll give both Alice and Bob the same kind of processor
    measure_noise_model = DephaseNoiseModel(dephase_rate=dephase_rate,
                                            time_independent=True)
    physical_instructions = [
        PhysicalInstruction(instr.INSTR_INIT, duration=3, parallel=True),
        PhysicalInstruction(instr.INSTR_H, duration=1, parallel=True, topology=[0, 1]),
        PhysicalInstruction(instr.INSTR_X, duration=1, parallel=True, topology=[0]),
        PhysicalInstruction(instr.INSTR_Z, duration=1, parallel=True, topology=[0]),
        PhysicalInstruction(instr.INSTR_S, duration=1, parallel=True, topology=[0]),
        PhysicalInstruction(instr.INSTR_CNOT, duration=4, parallel=True, topology=[(0, 1)]),
        PhysicalInstruction(instr.INSTR_MEASURE, duration=7, parallel=False, topology=[0],
                            quantum_noise_model=measure_noise_model, apply_q_noise_after=False),
        PhysicalInstruction(instr.INSTR_MEASURE, duration=7, parallel=False, topology=[1])
    ]
    memory_noise_model = DepolarNoiseModel(depolar_rate=depolar_rate)
    processor = QuantumProcessor("quantum_processor", num_positions=2,
                                 memory_noise_models=[memory_noise_model] * 2,
                                 phys_instructions=physical_instructions)
    return processor

from netsquid.components.qchannel import QuantumChannel
from netsquid.qubits import StateSampler
from netsquid.nodes.connections import Connection
from netsquid.components import ClassicalChannel
from netsquid.components.models import FibreDelayModel, FixedDelayModel
from netsquid.components.qsource import QSource, SourceStatus
import netsquid.qubits.ketstates as ks

class EntanglingConnection(Connection):
    """A connection that generates entanglement.

    Consists of a midpoint holding a quantum source that connects to
    outgoing quantum channels.

    Parameters
    ----------
    length : float
        End to end length of the connection [km].
    source_frequency : float
        Frequency with which midpoint entanglement source generates entanglement [Hz].
    name : str, optional
        Name of this connection.

    """

    def __init__(self, length, source_frequency, name="EntanglingConnection"):
        super().__init__(name=name)
        qsource = QSource(f"qsource_{name}", StateSampler([ks.b00], [1.0]), num_ports=2,
                          timing_model=FixedDelayModel(delay=1e9 / source_frequency),
                          status=SourceStatus.INTERNAL)
        self.add_subcomponent(qsource, name="qsource")
        qchannel_c2a = QuantumChannel("qchannel_C2A", length=length / 2,
                                      models={"delay_model": FibreDelayModel()})
        qchannel_c2b = QuantumChannel("qchannel_C2B", length=length / 2,
                                      models={"delay_model": FibreDelayModel()})
        # Add channels and forward quantum channel output to external port output:
        self.add_subcomponent(qchannel_c2a, forward_output=[("A", "recv")])
        self.add_subcomponent(qchannel_c2b, forward_output=[("B", "recv")])
        # Connect qsource output to quantum channel input:
        qsource.ports["qout0"].connect(qchannel_c2a.ports["send"])
        qsource.ports["qout1"].connect(qchannel_c2b.ports["send"])

class ClassicalConnection(Connection):
    """A connection that transmits classical messages in one direction, from A to B.

    Parameters
    ----------
    length : float
        End to end length of the connection [km].
    name : str, optional
       Name of this connection.

    """

    def __init__(self, length, name="ClassicalConnection"):
        super().__init__(name=name)
        self.add_subcomponent(ClassicalChannel("Channel_A2B", length=length,
                                               models={"delay_model": FibreDelayModel()}),
                              forward_input=[("A", "send")],
                              forward_output=[("B", "recv")])

from netsquid.components.qdetector import QuantumDetector
from netsquid.examples.simple_link import create_meas_ops
from netsquid.components.component import Message

class BSMDetector(QuantumDetector):
    """A component that performs Bell basis measurements.

    Measure two incoming qubits in the Bell basis if they
    arrive within the specified measurement delay.
    Only informs the connections that send a qubit of the measurement result.

    """

    def __init__(self, name, system_delay=0., dead_time=0., models=None,
                 output_meta=None, error_on_fail=False, properties=None):
        super().__init__(name, num_input_ports=2, num_output_ports=2,
                         meas_operators=create_meas_ops(),
                         system_delay=system_delay, dead_time=dead_time,
                         models=models, output_meta=output_meta,
                         error_on_fail=error_on_fail, properties=properties)
        self._sender_ids = []

    def preprocess_inputs(self):
        """Preprocess and capture the qubit metadata

        """
        super().preprocess_inputs()
        for port_name, qubit_list in self._qubits_per_port.items():
            if len(qubit_list) > 0:
                self._sender_ids.append(port_name[3:])

    def inform(self, port_outcomes):
        """Inform the MHP of the measurement result.

        We only send a result to the node that send a qubit.
        If the result is empty we change the result and header.

        Parameters
        ----------
        port_outcomes : dict
            A dictionary with the port names as keys
            and the post-processed measurement outcomes as values

        """
        for port_name, outcomes in port_outcomes.items():
            if len(outcomes) == 0:
                outcomes = ['TIMEOUT']
                header = 'error'
            else:
                header = 'photonoutcome'
            # Extract the ids from the port names (cout...)
            if port_name[4:] in self._sender_ids:
                msg = Message(outcomes, header=header, **self._meta)
                self.ports[port_name].tx_output(msg)

    def finish(self):
        """Clear sender ids after the measurement has finished."""
        super().finish()
        self._sender_ids.clear()

class HeraldedConnection(Connection):
    """A connection that takes in two qubits, and returns a message
    how they were measured at a detector.

    Either no clicks, a single click or double click, or an error
    when the qubits didn't arrive within the time window.

    Parameters
    ----------
    name : str
        The name of this connection
    length_to_a : float
        The length in km between the detector and side A. We assume a speed of 200000 km/s
    length_to_b : float
        The length in km between the detector and side B. We assume a speed of 200000 km/s
    time_window : float, optional
        The interval where qubits are still able to be measured correctly.
        Must be positive. Default is 0.

    """

    def __init__(self, name, length_to_a, length_to_b, time_window=0):
        super().__init__(name)
        delay_a = length_to_a / 200000 * 1e9
        delay_b = length_to_b / 200000 * 1e9
        channel_a = ClassicalChannel("ChannelA", delay=delay_a)
        channel_b = ClassicalChannel("ChannelB", delay=delay_b)
        qchannel_a = QuantumChannel("QChannelA", delay=delay_a)
        qchannel_b = QuantumChannel("QChannelB", delay=delay_b)
        # Add all channels as subcomponents
        self.add_subcomponent(channel_a)
        self.add_subcomponent(channel_b)
        self.add_subcomponent(qchannel_a)
        self.add_subcomponent(qchannel_b)
        # Add midpoint detector
        detector = BSMDetector("Midpoint", system_delay=time_window)
        self.add_subcomponent(detector)
        # Connect the ports
        self.ports['A'].forward_input(qchannel_a.ports['send'])
        self.ports['B'].forward_input(qchannel_b.ports['send'])
        qchannel_a.ports['recv'].connect(detector.ports['qin0'])
        qchannel_b.ports['recv'].connect(detector.ports['qin1'])
        channel_a.ports['send'].connect(detector.ports['cout0'])
        channel_b.ports['send'].connect(detector.ports['cout1'])
        channel_a.ports['recv'].forward_output(self.ports['A'])
        channel_b.ports['recv'].forward_output(self.ports['B'])
