"""
The `dagger.graph` module contains the DAG object. This is the
main object that you'll talk to when constructing a casual graph.
"""

import logging

import numpy as np
import pandas as pd
import networkx as nx
from graphviz import Digraph
from dagger.common import normalise


class DAG:
    """
    A `dagger.DAG` object describes a graphical model of a dataset. This
    object is generated from a pandas dataframe. Every column in the
    dataframe will result in a node/variable in the `dagger.DAG` object.

    ```
    from dagger import DAG
    from dagger.common import make_fake_df
    # let's start with a new dataset
    df = make_fake_df(4)
    dag = DAG(df).add_edge("a", "b").add_edge("b", "c").add_edge("c","d")
    ```
    """
    def __init__(self, dataframe: pd.DataFrame):
        """
        Create a new `dagger.DAG` from a dataframe.

        Inputs:

        - **dataframe**: pandas object that contains all variables

        Example:

        ```
        from dagger import DAG
        from dagger.common import make_fake_df
        # let's start with a new dataset
        df = make_fake_df(4)
        dag = DAG(df).add_edge("a", "b").add_edge("b", "c").add_edge("c","d")
        ```
        """
        self._df = dataframe
        self.graph = nx.DiGraph()
        for node in self._df.columns:
            self.graph.add_node(node)

    @property
    def undirected(self):
        """
        Fetch the `undirected` variant of the NetworkX graph. This can be
        useful when trying to determine all paths between two nodes.
        """
        return self.graph.to_undirected()

    @property
    def origin_nodes(self):
        """These nodes are nodes that do not have any edges going in."""
        return tuple(x for x in self.graph.nodes() if self.graph.in_degree(x) == 0)

    @property
    def marginal_table(self):
        """
        The marginal table is a table with all possible values and associated probability.
        """
        nodes = list(self.graph.nodes)
        logging.debug(f"about to calculate marginal table with nodes {nodes}")
        logging.debug(f"updating table for node {nodes[-1]}")
        marginal = self.calc_node_table(nodes.pop())
        logging.debug(f"current node table:\n{marginal}")
        logging.debug(f"current marginal table:\n{marginal}")
        for node in nodes:
            logging.debug(f"updating table for node {node}")
            logging.debug(f"current node table:\n{self.calc_node_table(node)}")
            marginal = self.merge_probs(marginal, self.calc_node_table(node))
            logging.debug(f"current marginal table:\n{marginal}")
        return marginal

    @property
    def nodes(self):
        """The nodes of the graph."""
        return list(self.graph.nodes)

    @property
    def edges(self):
        """The edges of the graph."""
        return list(self.graph.edges)

    def copy(self):
        """Returns a copy of the current DAG."""
        new_dag = DAG(self._df)
        new_dag.graph = self.graph
        return new_dag

    def undirected_paths(self, node_a, node_b):
        """
        Returns a list of all the paths that are between `node_a` and `node_b`.
        These paths do not take the direction into account and will turn the
        directed graph into an undirected one.
        """
        return list(nx.all_simple_paths(self.undirected, node_a, node_b))

    def calc_node_table(self, name):
        """
        Calculates probability table for a given node.

        Suppose we have graph `A -> B -> C`: `.calc_node_table("b")`
        call will calculate `P(B|A)` in the `probs` column of the result.

        ## Input

        - **name**: Name of a node/variable in the graph
        """
        parents = self.parents(name)
        tbl = self._df.copy()
        logging.debug(f"creating node table node={name} parents={parents}")

        def calculate_parents_size(dataf, groups=[]):
            return (dataf
                    .assign(count=1)
                    .groupby(groups)
                    .transform(np.sum)['count'])

        if len(parents) == 0:
            tbl = tbl.assign(parent_size=lambda d: d.shape[0])
        else:
            tbl = tbl.assign(parent_size=lambda d: calculate_parents_size(d, list(parents)))
        return (tbl
                .assign(node_size=lambda d: calculate_parents_size(d, list(parents) + [name]))
                .assign(prob=lambda d: d['node_size'] / d['parent_size'])
                [list(parents) + [name] + ["prob"]]
                .drop_duplicates()
                .reset_index(drop=True))

    def merge_probs(self, this_df, that_df):
        """
        Merges two probability dataframes while checking if nodes
        are connected in the graph.
        """
        common_cols = list(set(this_df.columns)
                           .intersection(set(that_df.columns))
                           .difference({"prob"}))
        if len(common_cols) == 0:
            columns = set(that_df.columns).difference({"prob"})
            loose_tables = []
            for c in columns:
                for value in self.calc_node_table(c)[c].values:
                    loose_tables.append(this_df.assign(**{c: value}))
            join_able = pd.concat(loose_tables)
            return self.merge_probs(join_able, that_df)
        return (this_df
                .set_index(common_cols)
                .join(that_df.set_index(common_cols), lsuffix="1", rsuffix="2")
                .assign(prob=lambda x: normalise(x.prob1 * x.prob2))
                .drop("prob1", axis=1)
                .drop("prob2", axis=1)
                .reset_index())

    def add_edge(self, source, sink):
        """
        Adds an edge to the graph.

        ## Input

        - **source**: Name of a node in the graph
        - **sink**: Name of a node in the graph

        ## Example

        ```
        from dagger import DAG
        from dagger.common import make_fake_df

        (DAG(dataframe=make_fake_df(4))
            .add_edge("a", "b")
            .add_edge("b", "c")
            .add_edge("c", "d"))
        ```
        """
        if source not in self._df.columns:
            raise ValueError(f"cause {source} not in dataframe")
        if sink not in self._df.columns:
            raise ValueError(f"effect {sink} not in dataframe")
        self.graph.add_edge(source, sink)
        logging.debug(f"created connection {source} -> {sink}")
        return self

    def children(self, node):
        """
        Return the children of a node.

        ## Input

        - **node**: Name of a node

        ## Example

        ```
        from dagger import DAG
        from dagger.common import make_fake_df

        dag = (DAG(dataframe=make_fake_df(4))
            .add_edge("a", "b")
            .add_edge("b", "c")
            .add_edge("c", "d"))

        dag.children("b") #outputs "c"
        dag.children("c") #outputs "d"
        ```
        """
        return set(self.graph.successors(node))

    def parents(self, node):
        """
        Return the parents of a node.

        ## Input

        - **node**: Name of a node

        ## Example

        ```
        from dagger import DAG
        from dagger.common import make_fake_df

        dag = (DAG(dataframe=make_fake_df(4))
            .add_edge("a", "b")
            .add_edge("b", "c")
            .add_edge("c", "d"))

        dag.children("b") #outputs "a"
        dag.children("c") #outputs "b"
        ```
        """
        return set(self.graph.predecessors(node))

    def connections(self, node):
        """
        Return all nodes connected to the one passed in.

        ## Input

        - **node**: Name of a node

        ## Example

        ```
        from dagger import DAG
        from dagger.common import make_fake_df

        dag = (DAG(dataframe=make_fake_df(4))
            .add_edge("a", "b")
            .add_edge("b", "c")
            .add_edge("c", "d"))

        dag.children("b") #outputs ["a","c"]
        dag.children("c") #outputs ["b","d"]
        ```
        """
        return set(list(self.children(node)) + list(self.parents(node)))

    def independences(self):
        """
        **NOT IMPLEMENTED YET**
        """
        # https://www.slideshare.net/duytungpham18/lecture-1-graphical-models
        pass

    def plot(self):
        """A pretty plotting function."""
        d = Digraph()
        d.attr(rankdir='LR')
        d.attr('node', shape='circle')
        for n in self.graph.nodes:
            d.node(n)
        for n1, n2 in self.graph.edges:
            d.edge(n1, n2)
        return d

    def nx_plot(self, **kwargs):
        """
        A customizable plotting function. The function comes from `networkx`.
        It merely wraps around the `nx.draw` method, documentation of this project
        can be found [here](https://networkx.github.io/documentation/stable/index.html).
        """
        nx.draw(self.graph, node_size=500, with_labels=True, node_color="white", **kwargs)
