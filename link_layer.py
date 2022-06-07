import netsquid as ns
from netsquid.nodes.network import Network
from netsquid.components.qprocessor import QuantumProcessor
from netsquid.qubits.qformalism import QFormalism
from utils.components import HeraldedConnection
from utils.protocols import MidpointHeraldingProtocol, EGProtocol, NetworkProtocol

def create_example_network(num_qubits=3):
    """Create the example network.

    Alice and Bob need a QuantumProcessor to store the qubits they produce.
    Their qubits are send through a heralded connection,
    which needs to be connected to Alice and Bob.
    It is assumed qubits are send to the connection,
    and it returns classical messages.
    In this example we won't use noise on the quantum memories,
    so instead of defining PhysicalInstructions we
    fallback to nonphysical ones.
    In order to synchronize their attempts a classical connection is added.

    Parameters
    ----------
    num_qubits : int
        The number of entangled qubit pairs we expect this network to make. Default 3.

    Returns
    -------
    :class:`~netsquid.nodes.network.Network`
        The example network for a simple link.

    """
    network = Network('SimpleLinkNetwork')
    nodes = network.add_nodes(['Alice', 'Bob'])
    distance = 2  # in km
    for node in nodes:
        node.add_subcomponent(QuantumProcessor(f'qmem_{node.name}',
                                               num_positions=num_qubits + 1,
                                               fallback_to_nonphysical=True))
    conn = HeraldedConnection("HeraldedConnection", length_to_a=distance / 2,
                              length_to_b=distance / 2, time_window=20)
    network.add_connection(nodes[0], nodes[1], connection=conn, label='quantum')
    network.add_connection(nodes[0], nodes[1], delay=distance / 200000 * 1e9, label='classical')
    return network

def setup_protocol(network):
    """Configure the protocols.

    Parameters
    ----------
    network : :class:`~netsquid.nodes.network.Network`
        The network to configure the protocols on. Should consist of two nodes
        called Alice and Bob.

    Returns
    -------
    :class:`~netsquid.protocols.protocol.Protocol`
        A protocol describing the complete simple link setup.

    """
    nodes = network.nodes
    # Setup Alice
    q_ports = network.get_connected_ports(*nodes, label='quantum')
    c_ports = network.get_connected_ports(*nodes, label='classical')
    alice_mhp = MidpointHeraldingProtocol(nodes['Alice'], 500, q_ports[0])
    alice_egp = EGProtocol(nodes['Alice'], c_ports[0])
    alice_egp.add_phys_layer(alice_mhp)
    # Setup Bob
    bob_mhp = MidpointHeraldingProtocol(nodes['Bob'], 470, q_ports[1])
    bob_egp = EGProtocol(nodes['Bob'], c_ports[1])
    bob_egp.add_phys_layer(bob_mhp)
    return NetworkProtocol("SimpleLinkProtocol", alice_egp, bob_egp)

def run_simulation():
    """Run the example simulation.

    """
    ns.sim_reset()
    ns.set_random_state(42)  # Set the seed so we get the same outcome
    ns.set_qstate_formalism(QFormalism.DM)
    network = create_example_network()
    protocol = setup_protocol(network)
    protocol.start()
    ns.sim_run()

if __name__ == "__main__":
    run_simulation()