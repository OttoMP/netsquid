import pandas, pydynaa
import netsquid as ns
import netsquid.qubits.qubitapi as qapi
from netsquid.util.datacollector import DataCollector
from netsquid.protocols.protocol import Signals
from netsquid.nodes.network import Network
from netsquid.nodes import Node
from utils.components import create_processor, ClassicalConnection, EntanglingConnection
from utils.protocols import BellMeasurementProtocol, CorrectionProtocol

def example_network_setup(node_distance=4e-3, depolar_rate=1e7, dephase_rate=0.2):
    """Setup the physical components of the quantum network.

    Parameters
    ----------
    node_distance : float, optional
        Distance between nodes.
    depolar_rate : float, optional
        Depolarization rate of qubits in memory.
    dephase_rate : float, optional
        Dephasing rate of physical measurement instruction.

    Returns
    -------
    :class:`~netsquid.nodes.node.Network`
        A Network with nodes "Alice" and "Bob",
        connected by an entangling connection and a classical connection

    """
    # Setup nodes Alice and Bob with quantum processor:
    alice = Node("Alice", qmemory=create_processor(depolar_rate, dephase_rate))
    bob = Node("Bob", qmemory=create_processor(depolar_rate, dephase_rate))
    # Create a network
    network = Network("Teleportation_network")
    network.add_nodes([alice, bob])
    # Setup classical connection between nodes:
    c_conn = ClassicalConnection(length=node_distance)
    network.add_connection(alice, bob, connection=c_conn, label="classical",
                           port_name_node1="cout_bob", port_name_node2="cin_alice")
    # Setup entangling connection between nodes:
    source_frequency = 4e4 / node_distance
    q_conn = EntanglingConnection(
        length=node_distance, source_frequency=source_frequency)
    port_ac, port_bc = network.add_connection(
        alice, bob, connection=q_conn, label="quantum",
        port_name_node1="qin_charlie", port_name_node2="qin_charlie")
    alice.ports[port_ac].forward_input(alice.qmemory.ports['qin1'])
    bob.ports[port_bc].forward_input(bob.qmemory.ports['qin0'])
    return network

def scalable_network_setup(node_names, ccon_list, qcon_list, node_distance=4e-3, depolar_rate=1e7, dephase_rate=0.2):
    '''
    Parameters
    ----------
    node_names : list string
        Name for each node in the network
    '''
    # Setup nodes Alice and Bob with quantum processor:
    list_nodes = [Node(name, qmemory=create_processor(depolar_rate, dephase_rate)) for name in node_names]
    
    # Create a network
    network = Network("Teleportation_network")
    network.add_nodes(list_nodes)
    
    # Setup classical connection between nodes:
    c_conn = ClassicalConnection(length=node_distance)
    for connection in ccon_list:
        network.add_connection(network.get_node(connection[0]), network.get_node(connection[1]), connection=c_conn, label="classical",
                           port_name_node1="cout_bob", port_name_node2="cin_alice")
    
    # Setup entangling connection between nodes:
    source_frequency = 4e4 / node_distance
    q_conn = EntanglingConnection(length=node_distance, source_frequency=source_frequency)
    for connection in qcon_list:
        port_ac, port_bc = network.add_connection(
                                    network.get_node(connection[0]), network.get_node(connection[1]), connection=q_conn, label="quantum",
                                    port_name_node1="qin_charlie", port_name_node2="qin_charlie")
        network.get_node(connection[0]).ports[port_ac].forward_input(network.get_node(connection[0]).qmemory.ports['qin1'])
        network.get_node(connection[1]).ports[port_bc].forward_input(network.get_node(connection[1]).qmemory.ports['qin0'])


    return network

def example_sim_setup(node_A, node_B):
    """Example simulation setup with data collector for teleportation protocol.

    Parameters
    ----------
    node_A : :class:`~netsquid.nodes.node.Node`
        Node corresponding to Alice.
    node_B : :class:`~netsquid.nodes.node.Node`
        Node corresponding to Bob.

    Returns
    -------
    :class:`~netsquid.protocols.protocol.Protocol`
        Alice's protocol.
    :class:`~netsquid.protocols.protocol.Protocol`
        Bob's protocol.
    :class:`~netsquid.util.datacollector.DataCollector`
        Data collector to record fidelity.

    """

    def collect_fidelity_data(evexpr):
        protocol = evexpr.triggered_events[-1].source
        mem_pos = protocol.get_signal_result(Signals.SUCCESS)
        qubit, = protocol.node.qmemory.pop(mem_pos)
        fidelity = qapi.fidelity(qubit, ns.y0, squared=True)
        qapi.discard(qubit)
        return {"fidelity": fidelity}

    protocol_alice = BellMeasurementProtocol(node_A)
    protocol_bob = CorrectionProtocol(node_B)
    dc = DataCollector(collect_fidelity_data)
    dc.collect_on(pydynaa.EventExpression(source=protocol_bob, event_type=Signals.SUCCESS.value))
    return protocol_alice, protocol_bob, dc

def run_experiment(num_runs, depolar_rates, distance=4e-3, dephase_rate=0.0):
    """Setup and run the simulation experiment.

    Parameters
    ----------
    num_runs : int
        Number of cycles to run teleportation for.
    depolar_rates : list of float
        List of depolarization rates to repeat experiment for.
    distance : float, optional
        Distance between nodes [km].
    dephase_rate : float, optional
        Dephasing rate of physical measurement instruction.

    Returns
    -------
    :class:`pandas.DataFrame`
        Dataframe with recorded fidelity data.

    """
    fidelity_data = pandas.DataFrame()
    for i, depolar_rate in enumerate(depolar_rates):
        ns.sim_reset()
        node_list = ["Alice", "Bob"]
        ccon_list = [("Alice", "Bob")]
        qcon_list = [("Alice", "Bob")]
        network = scalable_network_setup(node_list, ccon_list, qcon_list, distance, depolar_rate, dephase_rate)
        #network = example_network_setup(distance, depolar_rate, dephase_rate)
        node_a = network.get_node("Alice")
        node_b = network.get_node("Bob")
        protocol_alice, protocol_bob, dc = example_sim_setup(node_a, node_b)
        protocol_alice.start()
        protocol_bob.start()
        q_conn = network.get_connection(node_a, node_b, label="quantum")
        cycle_runtime = (q_conn.subcomponents["qsource"].subcomponents["internal_clock"]
                         .models["timing_model"].delay)
        ns.sim_run(cycle_runtime * num_runs + 1)
        df = dc.dataframe
        df['depolar_rate'] = depolar_rate
        fidelity_data = fidelity_data.append(df)
    return fidelity_data

def create_plot():
    """Show a plot of fidelity verus depolarization rate.

    """
    from matplotlib import pyplot as plt
    depolar_rates = [1e6 * i for i in range(0, 200, 10)]
    fidelities = run_experiment(num_runs=1000, distance=4e-3,
                                depolar_rates=depolar_rates, dephase_rate=0.0)
    plot_style = {'kind': 'scatter', 'grid': True,
                  'title': "Fidelity of the teleported quantum state"}
    data = fidelities.groupby("depolar_rate")['fidelity'].agg(
        fidelity='mean', sem='sem').reset_index()
    data.plot(x='depolar_rate', y='fidelity', yerr='sem', **plot_style)
    plt.show()

if __name__ == "__main__":
    create_plot()