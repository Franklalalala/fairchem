"""
Copyright (c) Meta Platforms, Inc. and affiliates.

This source code is licensed under the MIT license found in the
LICENSE file in the root directory of this source tree.
"""

from __future__ import annotations

import os

import numpy as np
import pytest
import torch
from ase import Atoms, db
from ase.io import read
from ase.neighborlist import NeighborList, NewPrimitiveNeighborList

from fairchem.core.modules.evaluator import min_diff
from fairchem.core.preprocessing import AtomsToGraphs


@pytest.fixture(scope="class")
def atoms_to_graphs_internals(request) -> None:
    atoms = read(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "atoms.json"),
        index=0,
        format="json",
    )
    atoms.info["stiffness_tensor"] = np.array(
        [
            [293, 121, 121, 0, 0, 0],
            [121, 293, 121, 0, 0, 0],
            [121, 121, 293, 0, 0, 0],
            [0, 0, 0, 146, 0, 0],
            [0, 0, 0, 0, 146, 0],
            [0, 0, 0, 0, 0, 146],
        ],
        dtype=float,
    )
    test_object = AtomsToGraphs(
        max_neigh=200,
        radius=6,
        r_energy=True,
        r_forces=True,
        r_stress=True,
        r_distances=True,
        r_data_keys=["stiffness_tensor"],
    )
    test_object_only_stiffness = AtomsToGraphs(
        max_neigh=200,
        radius=6,
        r_energy=False,
        r_forces=False,
        r_stress=False,
        r_distances=False,
        r_data_keys=["stiffness_tensor"],
    )
    request.cls.atg = test_object
    request.cls.atg_only_stiffness = test_object_only_stiffness
    request.cls.atoms = atoms


@pytest.mark.usefixtures("atoms_to_graphs_internals")
class TestAtomsToGraphs:
    def test_gen_neighbors_pymatgen(self) -> None:
        # call the internal function
        (
            c_index,
            n_index,
            n_distances,
            offsets,
        ) = self.atg._get_neighbors_pymatgen(self.atoms)
        edge_index, edge_distances, cell_offsets = self.atg._reshape_features(
            c_index, n_index, n_distances, offsets
        )

        # use ase to compare distances and indices
        n = NeighborList(
            cutoffs=[self.atg.radius / 2.0] * len(self.atoms),
            self_interaction=False,
            skin=0,
            bothways=True,
            primitive=NewPrimitiveNeighborList,
        )
        n.update(self.atoms)
        ase_neighbors = [n.get_neighbors(index) for index in range(len(self.atoms))]
        ase_s_index = []
        ase_n_index = []
        ase_offsets = []
        for i, n in enumerate(ase_neighbors):
            nidx = n[0]
            ncount = len(nidx)
            ase_s_index += [i] * ncount
            ase_n_index += nidx.tolist()
            ase_offsets.append(n[1])
        ase_s_index = np.array(ase_s_index)
        ase_n_index = np.array(ase_n_index)
        ase_offsets = np.concatenate(ase_offsets)
        # compute ase distance
        cell = self.atoms.cell
        positions = self.atoms.positions
        distance_vec = positions[ase_s_index] - positions[ase_n_index]
        _offsets = np.dot(ase_offsets, cell)
        distance_vec -= _offsets
        act_dist = np.linalg.norm(distance_vec, axis=-1)

        act_dist = np.sort(act_dist)
        act_index = np.sort(ase_n_index)
        test_dist = np.sort(edge_distances)
        test_index = np.sort(edge_index[0, :])
        # check that the distance and neighbor index values are correct
        np.testing.assert_allclose(act_dist, test_dist)
        np.testing.assert_array_equal(act_index, test_index)

    def test_convert(self) -> None:
        # run convert on a single atoms obj
        data = self.atg.convert(self.atoms)
        # atomic numbers
        act_atomic_numbers = self.atoms.get_atomic_numbers()
        atomic_numbers = data.atomic_numbers.numpy()
        np.testing.assert_equal(act_atomic_numbers, atomic_numbers)
        # positions
        act_positions = self.atoms.get_positions()
        positions = data.pos.numpy()
        mindiff = min_diff(
            act_positions, positions, self.atoms.get_cell(), self.atoms.pbc
        )
        np.testing.assert_allclose(mindiff, 0, atol=1e-6)
        # check energy value
        act_energy = self.atoms.get_potential_energy(apply_constraint=False)
        test_energy = data.energy
        np.testing.assert_equal(act_energy, test_energy)
        # forces
        act_forces = self.atoms.get_forces(apply_constraint=False)
        forces = data.forces.numpy()
        np.testing.assert_allclose(act_forces, forces)
        # stress
        act_stress = self.atoms.get_stress(apply_constraint=False, voigt=False)
        stress = data.stress.numpy()
        np.testing.assert_allclose(act_stress, stress)
        # additional data (ie stiffness_tensor)
        stiffness_tensor = data.stiffness_tensor.numpy()
        np.testing.assert_allclose(
            self.atoms.info["stiffness_tensor"], stiffness_tensor
        )

    def test_convert_all_atoms_list(self) -> None:
        # run convert_all on a list with one atoms object
        atoms_list = [self.atoms]
        data_list = self.atg.convert_all(atoms_list)
        # check shape/values of features
        # atomic numbers
        act_atomic_nubmers = self.atoms.get_atomic_numbers()
        atomic_numbers = data_list[0].atomic_numbers.numpy()
        np.testing.assert_equal(act_atomic_nubmers, atomic_numbers)
        # positions
        act_positions = self.atoms.get_positions()
        positions = data_list[0].pos.numpy()
        mindiff = min_diff(
            act_positions, positions, self.atoms.get_cell(), self.atoms.pbc
        )
        np.testing.assert_allclose(mindiff, 0, atol=1e-6)
        # check energy value
        act_energy = self.atoms.get_potential_energy(apply_constraint=False)
        test_energy = data_list[0].energy
        np.testing.assert_equal(act_energy, test_energy)
        # forces
        act_forces = self.atoms.get_forces(apply_constraint=False)
        forces = data_list[0].forces.numpy()
        np.testing.assert_allclose(act_forces, forces)
        # stress
        act_stress = self.atoms.get_stress(apply_constraint=False, voigt=False)
        stress = data_list[0].stress.numpy()
        np.testing.assert_allclose(act_stress, stress)
        # additional data (ie stiffness_tensor)
        stiffness_tensor = data_list[0].stiffness_tensor.numpy()
        np.testing.assert_allclose(
            self.atoms.info["stiffness_tensor"], stiffness_tensor
        )

    def test_convert_all_ase_db(self, tmp_path_factory) -> None:
        # run convert_all on an ASE db object

        # There is a possible bug in ASE which makes this test annoying to write.
        # AtomsRow.toatoms() has a calculator attached that computes a stress tensor # with the wrong shape: (9,). This makes convert_all fail due to an assertion in
        # atoms.get_stress().

        tmp_path = tmp_path_factory.mktemp("convert_all_test")
        with db.connect(tmp_path / "asedb.db") as database:
            database.write(self.atoms, data=self.atoms.info)
            data_list = self.atg_only_stiffness.convert_all(database)

        # additional data (ie stiffness_tensor)
        stiffness_tensor = data_list[0].stiffness_tensor.numpy()
        np.testing.assert_allclose(
            self.atoms.info["stiffness_tensor"], stiffness_tensor
        )

    def test_convert_molecule(self) -> None:
        # test converting a molecule with no unit cell
        molecule = Atoms("2N", [(0.0, 0.0, 0.0), (0.0, 0.0, 1.0)])
        a2g = AtomsToGraphs(
            max_neigh=200,
            radius=6,
            r_edges=True,
            r_distances=True,
        )
        # this will raise an Singlular Matrix Error because the cell doesn't exist
        with pytest.raises(np.linalg.LinAlgError):
            a2g.convert(molecule)
        # now add a molecular box
        cell_size = 120.0
        a2g = AtomsToGraphs(
            max_neigh=200,
            radius=6,
            r_edges=True,
            r_distances=True,
            molecule_cell_size=cell_size,
        )
        converted_mol = a2g.convert(molecule)
        assert torch.allclose(
            converted_mol.cell[0],
            torch.diag(torch.tensor([cell_size * 2, cell_size * 2, cell_size * 2 + 1])),
        )
        assert converted_mol.natoms == 2
        assert torch.allclose(
            converted_mol.pos[0], torch.tensor([cell_size, cell_size, cell_size])
        )
        assert torch.allclose(
            converted_mol.pos[1], torch.tensor([cell_size, cell_size, cell_size + 1])
        )
        assert torch.allclose(converted_mol.edge_index, torch.tensor([[1, 0], [0, 1]]))

    def test_convert_molecule_raises_assertion_with_cell(self) -> None:
        molecule = Atoms("2N", [(0.0, 0.0, 0.0), (0.0, 0.0, 1.0)], cell=[1, 1, 1])
        a2g = AtomsToGraphs(
            molecule_cell_size=120.0,
            r_distances=True,
        )
        with pytest.raises(AssertionError):
            a2g.convert(molecule)
