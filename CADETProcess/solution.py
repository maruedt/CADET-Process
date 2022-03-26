"""Store and plot solution of simulation.

NCOL/N_Z: Number of axial cells
z: Axial position

NRAD/N_rho: Number of
rho: Annulus cell (cylinder shell)

NCOMP/N_C: Number of components
i: component index

NPARTYPE/N_P: Number of particle types
j: Particle type index

NPAR/N_R: Number of particle cells
r: Radial position (particle)

IO: NCOL * NRAD
Bulk/Interstitial: NCOL * NRAD * NCOMP
Particle_liquid: NCOL * NRAD * sum_{j}^{NPARTYPE}{NCOMP * NPAR,j}
Particle_solid: NCOL * NRAD * sum_{j}^{NPARTYPE}{NBOUND,j * NPAR,j}
Flux: NCOL * NRAD * NPARTYPE * NCOMP
"""

import numpy as np
import matplotlib.pyplot as plt
from scipy.interpolate import InterpolatedUnivariateSpline

from CADETProcess.dataStructure import StructMeta
from CADETProcess.dataStructure import (
    String, UnsignedInteger, Vector, DependentlySizedNdArray
)
from CADETProcess.processModel import ComponentSystem
from CADETProcess import plotting


class SolutionBase(metaclass=StructMeta):
    name = String()
    time = Vector()
    solution = DependentlySizedNdArray(dep='solution_shape')

    _coordinates = []

    def __init__(self, name, component_system, time, solution):
        self.name = name
        self.component_system = component_system
        self.time = time
        self.solution = solution

    @property
    def component_system(self):
        return self._component_system

    @component_system.setter
    def component_system(self, component_system):
        if not isinstance(component_system, ComponentSystem):
            raise TypeError('Expected ComponentSystem')
        self._component_system = component_system

    @property
    def n_comp(self):
        return self.component_system.n_comp

    @property
    def cycle_time(self):
        return self.time[-1]

    @property
    def nt(self):
        return len(self.time)

    @property
    def coordinates(self):
        coordinates = {}

        for c in self._coordinates:
            v = getattr(self, c)
            if v is None:
                continue
            coordinates[c] = v
        return coordinates

    @property
    def solution_shape(self):
        """tuple: (Expected) shape of the solution
        """
        coordinates = tuple(len(c) for c in self.coordinates.values())
        return (self.nt,) + coordinates + (self.n_comp,)

    @property
    def total_concentration_components(self):
        """np.array: Total concentration of components (sum of species)."""
        return component_concentration(self.component_system, self.solution)

    @property
    def total_concentration(self):
        """np.array: Total concentration all of components."""
        return total_concentration(self.component_system, self.solution)

    @property
    def local_purity_components(self):
        return purity(self.component_system, self.solution, sum_species=False)

    @property
    def local_purity_species(self):
        """np.array: Local purity of components."""
        return purity(self.component_system, self.solution, sum_species=False)


class SolutionIO(SolutionBase):
    """Solution at unit inlet or outlet.

    IO: NCOL * NRAD

    """

    def __init__(self, name, component_system, time, solution, flow_rate):
        self.name = name
        self.component_system = component_system
        self.time = time
        self.solution = solution

        self.flow_rate = flow_rate

        vec_q_value = np.vectorize(flow_rate.value)
        q_vector = vec_q_value(time)
        dm_dt = solution * q_vector[:, None]

        self.interpolated_dm_dt = InterpolatedSignal(self.time, dm_dt)
        self.interpolated_Q = InterpolatedUnivariateSpline(time, q_vector)

    def fraction_mass(self, start, end):
        """Component mass in a fraction interval

        Parameters
        ----------
        start : float
            Start time of the fraction

        end: float
            End time of the fraction

        Returns
        -------
        fraction_mass : np.array
            Mass of all components in the fraction

        """
        return self.interpolated_dm_dt.integral(start, end)

    def fraction_volume(self, start, end):
        """Volume of a fraction interval

        Parameters
        ----------
        start : float
            Start time of the fraction

        end: float
            End time of the fraction

        Returns
        -------
        fraction_volume : np.array
            Volume of the fraction

        """
        return self.interpolated_Q.integral(start, end)

    @plotting.create_and_save_figure
    def plot(
            self,
            start=0, end=None, y_max=None,
            layout=None,
            only_plot_total_concentrations=False,
            alpha=1, hide_labels=False,
            secondary_axis=None, secondary_layout=None,
            show_legend=True,
            ax=None):
        """Plots the whole time_signal for each component.

        Parameters
        ----------
        start : float
            start time for plotting
        end : float
            end time for plotting
        ax : Axes
            Axes to plot on.

        Returns
        -------
        ax : Axes
            Axes object with buffer capacity plot.

        See Also
        --------
        plotlib
        plot_purity
        """
        if layout is None:
            layout = plotting.Layout()
            layout.x_label = '$time~/~min$'
            layout.y_label = '$c~/~mM$'
            layout.x_lim = (start, end)

        ax = _plot_solution_1D(
            self,
            layout=layout,
            only_plot_total_concentrations=only_plot_total_concentrations,
            alpha=alpha,
            hide_labels=hide_labels,
            secondary_axis=secondary_axis,
            secondary_layout=secondary_layout,
            show_legend=show_legend,
            ax=ax,
        )

        return ax

    @plotting.create_and_save_figure
    def plot_purity(
            self,
            start=0, end=None, y_max=None,
            layout=None,
            only_plot_total_concentrations=False,
            alpha=1, hide_labels=False,
            secondary_axis=None, secondary_layout=None,
            show_legend=True,
            ax=None):
        """Plot local purity for each component of the concentration profile.

        Parameters
        ----------
        start : float
            start time for plotting
        end : float
            end time for plotting
        ax : Axes
            Axes to plot on.

        Returns
        -------
        ax : Axes
            Axes with plot of purity over time.

        See Also
        --------
        plotlib
        plot

        """

        time = self.time / 60
        sol = self.local_purity * 100

        if layout is None:
            layout = plotting.Layout()
            layout.x_label = '$time~/~min$'
            layout.y_label = '$Purity ~/~\%$'
            layout.x_lim = (start, end)
            layout.y_lim = (np.min(sol), 1.1*np.max(sol))

        total_concentration = self.total_concentration

        if secondary_axis is not None:
            ax_secondary = ax.twinx()
        else:
            ax_secondary = None

        species_index = 0
        y_min = 0
        y_max = 0
        y_min_sec = 0
        y_max_sec = 0
        for i, comp in enumerate(self.component_system.components):
            color = next(ax._get_lines.prop_cycler)['color']
            if hide_labels:
                label = None
            else:
                label = comp.name

            if secondary_axis is not None \
                    and i in secondary_axis.component_indices:
                a = ax_secondary
            else:
                a = ax

            if secondary_axis is not None \
                    and secondary_axis.transform is not None \
                    and i in secondary_axis.component_indices:
                y = secondary_axis.transform(total_concentration[..., i])
            else:
                y = total_concentration[..., i]

            if secondary_axis is not None \
                    and i in secondary_axis.component_indices:
                y_min_sec = min(min(y), y_min_sec)
                y_max_sec = max(max(y), y_max_sec)
            else:
                y_min = min(min(y), y_min)
                y_max = max(max(y), y_max)

            a.plot(
                time, y,
                label=label,
                color=color,
                alpha=alpha
            )

            if not only_plot_total_concentrations:
                if comp.n_species == 1:
                    species_index += 1
                    continue

                for s, species in enumerate(comp.species):
                    label = s
                    if secondary_axis is not None \
                            and i in secondary_axis.component_indices:
                        a = ax_secondary
                    else:
                        a = ax

                    if secondary_axis is not None \
                            and secondary_axis.transform is not None \
                            and i in secondary_axis.component_indices:
                        y = secondary_axis.transform(sol[..., species_index])
                    else:
                        y = sol[..., species_index]

                    a.plot(
                        time, y, '--',
                        label=label,
                        color=color,
                        alpha=alpha
                    )
                    species_index += 1
        if layout.y_lim is None:
            layout.y_lim = (y_min, 1.1*y_max)

        if secondary_axis is not None and secondary_layout is None:
            secondary_layout = plotting.Layout()
            secondary_layout.y_label = secondary_axis.y_label
            secondary_layout.y_lim = (y_min_sec, 1.1*y_max_sec)

        plotting.set_layout(
            ax,
            layout,
            show_legend,
            ax_secondary,
            secondary_layout,
        )

        return ax


class SolutionBulk(SolutionBase):
    """Interstitial solution.

    Bulk/Interstitial: NCOL * NRAD * NCOMP
    """
    _coordinates = ['axial_coordinates', 'radial_coordinates']

    def __init__(
            self,
            name,
            component_system,
            time, solution,
            axial_coordinates=None, radial_coordinates=None
            ):
        self.name = name
        self.component_system = component_system
        self.time = time
        self.axial_coordinates = axial_coordinates
        # Account for dimension reduction in case of only one cell (e.g. LRMP)
        if radial_coordinates is not None and len(radial_coordinates) == 1:
            radial_coordinates = None
        self.radial_coordinates = radial_coordinates
        self.solution = solution

    @property
    def ncol(self):
        if self.axial_coordinates is None:
            return
        return len(self.axial_coordinates)

    @property
    def nrad(self):
        if self.radial_coordinates is None:
            return
        return len(self.radial_coordinates)

    @plotting.create_and_save_figure
    def plot_at_time(self, t, overlay=None, y_min=None, y_max=None, ax=None):
        """Plot bulk solution over space at given time.

        Parameters
        ----------
        t : float
            time for plotting
        ax : Axes
            Axes to plot on.

        See Also
        --------
        plot_at_location
        CADETProcess.plotting
        """
        x = self.axial_coordinates

        if not self.time[0] <= t <= self.time[-1]:
            raise ValueError("Time exceeds bounds.")
        t_i = np.where(t <= self.time)[0][0]

        y = self.solution[t_i, :]
        if y_max is None:
            y_max = 1.1*np.max(y)
        if y_min is None:
            y_min = min(0, np.min(y))

        ax.plot(x, y)

        plotting.add_text(ax, f'time = {t:.2f} s')

        if overlay is not None:
            y_max = np.max(overlay)
            plotting.add_overlay(ax, overlay)

        layout = plotting.Layout()
        layout.x_label = '$z~/~m$'
        layout.y_label = '$c~/~mM$'
        layout.y_lim = (y_min, y_max)
        plotting.set_layout(ax, layout)

        return ax

    @plotting.create_and_save_figure
    def plot_at_location(
            self, z, overlay=None, y_min=None, y_max=None, ax=None):
        """Plot bulk solution over time at given location.

        Parameters
        ----------
        z : float
            space for plotting
        ax : Axes
            Axes to plot on.

        See Also
        --------
        plot_at_time
        CADETProcess.plotting
        """
        x = self.time

        if not self.axial_coordinates[0] <= z <= self.axial_coordinates[-1]:
            raise ValueError("Axial coordinate exceets boundaries.")
        z_i = np.where(z <= self.axial_coordinates)[0][0]

        y = self.solution[:, z_i]
        if y_max is None:
            y_max = 1.1*np.max(y)
        if y_min is None:
            y_min = min(0, np.min(y))

        ax.plot(x, y)

        plotting.add_text(ax, f'z = {z:.2f} m')

        if overlay is not None:
            y_max = np.max(overlay)
            plotting.add_overlay(ax, overlay)

        layout = plotting.Layout()
        layout.x_label = '$time~/~min$'
        layout.y_label = '$c~/~mM$'
        layout.y_lim = (y_min, y_max)
        plotting.set_layout(ax, layout)

        return ax


class SolutionParticle(SolutionBase):
    """Mobile phase solution inside the particles.

    Particle_liquid: NCOL * NRAD * sum_{j}^{NPARTYPE}{NCOMP * NPAR,j}
    """

    _coordinates = [
        'axial_coordinates', 'radial_coordinates', 'particle_coordinates'
    ]

    def __init__(
            self,
            name,
            component_system,
            time, solution,
            axial_coordinates=None,
            radial_coordinates=None,
            particle_coordinates=None
            ):
        self.name = name
        self.component_system = component_system
        self.time = time
        self.axial_coordinates = axial_coordinates
        # Account for dimension reduction in case of only one cell (e.g. LRMP)
        if radial_coordinates is not None and len(radial_coordinates) == 1:
            radial_coordinates = None
        self.radial_coordinates = radial_coordinates
        # Account for dimension reduction in case of only one cell (e.g. CSTR)
        if particle_coordinates is not None and len(particle_coordinates) == 1:
            particle_coordinates = None
        self.particle_coordinates = particle_coordinates
        self.solution = solution

    @property
    def ncol(self):
        if self.axial_coordinates is None:
            return
        return len(self.axial_coordinates)

    @property
    def nrad(self):
        if self.radial_coordinates is None:
            return
        return len(self.radial_coordinates)

    @property
    def npar(self):
        if self.particle_coordinates is None:
            return
        return len(self.particle_coordinates)

    def _plot_1D(self, t, ymax, ax=None):
        x = self.axial_coordinates

        if not self.time[0] <= t <= self.time[-1]:
            raise ValueError("Time exceeds bounds.")
        t_i = np.where(t <= self.time)[0][0]
        y = self.solution[t_i, :]

        if ymax is None:
            ymax = 1.1*np.max(y)

        ax.plot(x, y)

        plotting.add_text(ax, f'time = {t:.2f} s')

        layout = plotting.Layout()
        layout.x_label = '$z~/~m$'
        layout.y_label = '$c~/~mM$'
        layout.y_lim = (0, ymax)
        plotting.set_layout(ax, layout)

        return ax

    def _plot_2D(self, t, comp, vmax, ax=None):
        x = self.axial_coordinates
        y = self.particle_coordinates

        if not self.time[0] <= t <= self.time[-1]:
            raise ValueError("Time exceeds bounds.")
        i = np.where(t <= self.time)[0][0]
        v = self.solution[i, :, :, comp].transpose()

        if vmax is None:
            vmax = v.max()
        try:
            mesh = ax.get_children()[0]
            mesh.set_array(v.flatten())
        except:
            mesh = ax.pcolormesh(x, y, v, shading='gouraud', vmin=0, vmax=vmax)

        plotting.add_text(ax, f'time = {t:.2f} s')

        layout = plotting.Layout()
        layout.x_label = '$z~/~m$'
        layout.y_label = '$r~/~m$'
        layout.title = f'Solid phase concentration, comp={comp}'

        plotting.set_layout(ax, layout)
        plt.colorbar(mesh)

        return ax

    @plotting.create_and_save_figure
    def plot_at_time(self, t, comp=0, vmax=None, ax=None):
        """Plot particle liquid solution over space at given time.

        Parameters
        ----------
        t : float
            time for plotting
        comp : int
            component index
        ax : Axes
            Axes to plot on.

        See Also
        --------
        CADETProcess.plotting
        """
        if self.npar is None:
            ax = self._plot_1D(ax, t, vmax)
        else:
            ax = self._plot_2D(ax, t, comp, vmax)

        return ax


class SolutionSolid(SolutionBase):
    """Solid phase solution inside the particles.

    Particle_solid: NCOL * NRAD * sum_{j}^{NPARTYPE}{NBOUND,j * NPAR,j}
    """

    n_bound = UnsignedInteger()

    _coordinates = [
        'axial_coordinates', 'radial_coordinates', 'particle_coordinates'
    ]

    def __init__(
            self,
            name,
            component_system, n_bound,
            time, solution,
            axial_coordinates=None,
            radial_coordinates=None,
            particle_coordinates=None):
        self.name = name
        self.component_system = component_system
        self.n_bound = n_bound
        self.time = time
        self.axial_coordinates = axial_coordinates
        # Account for dimension reduction in case of only one cell (e.g. LRMP)
        if radial_coordinates is not None and len(radial_coordinates) == 1:
            radial_coordinates = None
        self.radial_coordinates = radial_coordinates
        # Account for dimension reduction in case of only one cell (e.g. CSTR)
        if particle_coordinates is not None and len(particle_coordinates) == 1:
            particle_coordinates = None
        self.particle_coordinates = particle_coordinates
        self.solution = solution

    @property
    def n_comp(self):
        return self.component_system.n_comp * self.n_bound

    @property
    def ncol(self):
        if self.axial_coordinates is None:
            return None
        else:
            return len(self.axial_coordinates)

    @property
    def nrad(self):
        if self.radial_coordinates is None:
            return
        return len(self.radial_coordinates)

    @property
    def npar(self):
        if self.particle_coordinates is None:
            return
        return len(self.particle_coordinates)

    def _plot_1D(self, t, y_min=None, y_max=None, ax=None):
        x = self.axial_coordinates

        if not self.time[0] <= t <= self.time[-1]:
            raise ValueError("Time exceeds bounds.")
        t_i = np.where(t <= self.time)[0][0]
        y = self.solution[t_i, :]

        if y_max is None:
            y_max = 1.1*np.max(y)
        if y_min is None:
            y_min = min(0, np.min(y))

        ax.plot(x, y)

        plotting.add_text(ax, f'time = {t:.2f} s')

        layout = plotting.Layout()
        layout.x_label = '$z~/~m$'
        layout.y_label = '$c~/~mM$'
        layout.labels = self.component_system.labels
        layout.y_lim = (y_min, y_max)
        plotting.set_layout(ax, layout)

        return ax

    def _plot_2D(self, t, comp, state, vmax, ax=None):
        x = self.axial_coordinates
        y = self.particle_coordinates

        if not self.time[0] <= t <= self.time[-1]:
            raise ValueError("Time exceeds bounds.")
        t_i = np.where(t <= self.time)[0][0]
        c_i = comp*self.n_bound + state
        v = self.solution[t_i, :, :, c_i].transpose()

        if vmax is None:
            vmax = v.max()

        mesh = ax.pcolormesh(x, y, v, shading='gouraud', vmin=0, vmax=vmax)

        plotting.add_text(ax, f'time = {t:.2f} s')

        layout = plotting.Layout()
        layout.title = f'Solid phase concentration, comp={comp}, state={state}'
        layout.x_label = '$z~/~m$'
        layout.y_label = '$r~/~m$'
        layout.labels = self.component_system.labels[c_i]
        plotting.set_layout(ax, layout)

        return ax, mesh

    @plotting.create_and_save_figure
    def plot_at_time(self, t, comp=0, state=0, vmax=None, ax=None):
        """Plot particle solid solution over space at given time.

        Parameters
        ----------
        t : float
            time for plotting
        comp : int, optional
            component index
        state : int, optional
            bound state
        vmax : float, optional
            Maximum values for plotting.
        ax : Axes
            Axes to plot on.

        See Also
        --------
        CADETProcess.plotting
        """
        if self.npar is None:
            ax = self._plot_1D(ax, t, vmax)
        else:
            ax, mesh = self._plot_2D(ax, t, comp, vmax)
            plt.colorbar(mesh, ax)
        return ax


class SolutionVolume(SolutionBase):
    """Volume solution (of e.g. CSTR)."""

    def __init__(self, name, component_system, time, solution):
        self.name = name
        self.time = time
        self.solution = solution

    @property
    def solution_shape(self):
        """tuple: (Expected) shape of the solution"""
        return (self.nt, 1)

    @plotting.create_and_save_figure
    def plot(self, start=0, end=None, overlay=None, ax=None):
        """Plot the whole time_signal for each component.

        Parameters
        ----------
        start : float
            start time for plotting
        end : float
            end time for plotting
        ax : Axes
            Axes to plot on.

        See Also
        --------
        CADETProcess.plot
        """
        x = self.time / 60
        y = self.solution * 1000

        y_min = np.min(y)
        y_max = np.max(y)

        ax.plot(x, y)

        if overlay is not None:
            y_max = 1.1*np.max(overlay)
            plotting.add_overlay(ax, overlay)

        layout = plotting.Layout()
        layout.x_label = '$time~/~min$'
        layout.y_label = '$V~/~L$'
        layout.x_lim = (start, end)
        layout.y_lim = (y_min, y_max)
        plotting.set_layout(ax, layout)

        return ax


def _plot_solution_1D(
        solution,
        layout=None,
        only_plot_total_concentrations=False,
        alpha=1, hide_labels=False, hide_species_labels=True,
        secondary_axis=None, secondary_layout=None,
        show_legend=True,
        ax=None):

    time = solution.time / 60
    sol = solution.solution

    c_total_comp = solution.total_concentration_components

    if secondary_axis is not None:
        ax_secondary = ax.twinx()
    else:
        ax_secondary = None

    species_index = 0
    y_min = 0
    y_max = 0
    y_min_sec = 0
    y_max_sec = 0
    for i, comp in enumerate(solution.component_system.components):
        color = next(ax._get_lines.prop_cycler)['color']
        if hide_labels:
            label = None
        else:
            label = comp.name

        if secondary_axis is not None \
                and i in secondary_axis.component_indices:
            a = ax_secondary
        else:
            a = ax

        if secondary_axis is not None \
                and secondary_axis.transform is not None \
                and i in secondary_axis.component_indices:
            y = secondary_axis.transform(c_total_comp[..., i])
        else:
            y = c_total_comp[..., i]

        if secondary_axis is not None \
                and i in secondary_axis.component_indices:
            y_min_sec = min(min(y), y_min_sec)
            y_max_sec = max(max(y), y_max_sec)
        else:
            y_min = min(min(y), y_min)
            y_max = max(max(y), y_max)

        a.plot(
            time, y,
            label=label,
            color=color,
            alpha=alpha
        )

        if not only_plot_total_concentrations:
            if comp.n_species == 1:
                species_index += 1
                continue

            for s, species in enumerate(comp.species):
                if hide_species_labels:
                    label = None
                else:
                    label = s
                if secondary_axis is not None \
                        and i in secondary_axis.component_indices:
                    a = ax_secondary
                else:
                    a = ax

                if secondary_axis is not None \
                        and secondary_axis.transform is not None \
                        and i in secondary_axis.component_indices:
                    y = secondary_axis.transform(sol[..., species_index])
                else:
                    y = sol[..., species_index]

                a.plot(
                    time, y, '--',
                    label=label,
                    color=color,
                    alpha=alpha
                )
                species_index += 1
    if layout.y_lim is None:
        layout.y_lim = (y_min, 1.1*y_max)

    if secondary_axis is not None and secondary_layout is None:
        secondary_layout = plotting.Layout()
        secondary_layout.y_label = secondary_axis.y_label
        secondary_layout.y_lim = (y_min_sec, 1.1*y_max_sec)

    plotting.set_layout(
        ax,
        layout,
        show_legend,
        ax_secondary,
        secondary_layout,
    )

    return ax


class InterpolatedSignal():
    def __init__(self, time, signal):
        self._signal = [
                InterpolatedUnivariateSpline(time, signal[:, comp])
                for comp in range(signal.shape[1])
                ]

    def integral(self, start, end):
        return np.array([
            self._signal[comp].integral(start, end)
            for comp in range(len(self._signal))
        ])

    def __call__(self, t):
        return np.array([
            self._signal[comp](t) for comp in range(len(self._signal))
        ])


def purity(
        component_system, solution,
        sum_species=True, min_value=1e-6, exclude=None):
    """Local purity profile of solution.

    Parameters
    ----------
    component_system : ComponentSystem
        DESCRIPTION.
    solution : np.array
        Array containing concentrations.
    sum_species : bool, optional
        DESCRIPTION. The default is True.
    min_value : float, optional
        Minimum concentration to be considered. Everything below min_value
        will be considered as 0. The default is 1e-6.
    exclude : list, optional
        List of component names to be excluded from purity calculation.
        The default is None.

    Returns
    -------
    purity
        Local purity of components/species.

    """
    if exclude is None:
        exclude = []

    c_total = total_concentration(component_system, solution, exclude)

    if sum_species:
        solution = component_concentration(component_system, solution)

    purity = np.zeros(solution.shape)

    c_total[c_total < min_value] = np.nan

    for i, comp in enumerate(component_system):
        if comp.name in exclude:
            continue

        s = solution[:, i]
        with np.errstate(divide='ignore', invalid='ignore'):
            purity[:, i] = np.divide(s, c_total)

    purity = np.nan_to_num(purity)

    return np.nan_to_num(purity)


def component_concentration(component_system, solution):
    """Compute total concentration of components by summing up species.

    Parameters
    ----------
    component_system : ComponentSystem
        ComponentSystem containing information about subspecies.
    solution : np.array
        Solution array.

    Returns
    -------
    component_concentration : np.array
        Total concentration of components.

    """
    component_concentration = np.zeros(
        solution.shape[0:-1] + (component_system.n_components,)
    )

    counter = 0
    for index, comp in enumerate(component_system):
        comp_indices = slice(counter, counter+comp.n_species)
        c_total = np.sum(solution[..., comp_indices], axis=1)
        component_concentration[:, index] = c_total
        counter += comp.n_species

    return component_concentration


def total_concentration(component_system, solution, exclude=None):
    """Compute total concentration of all components.

    Parameters
    ----------
    component_system : ComponentSystem
        ComponentSystem containing information about subspecies.
    solution : np.array
        Solution array.
    Exclude : list
        Component names to be excluded from total concentration.

    Returns
    -------
    total_concentration : np.array
        Total concentration of all components.

    """
    if exclude is None:
        exclude = []

    total_concentration = np.zeros(solution.shape[0:-1])

    counter = 0
    for index, comp in enumerate(component_system):
        if comp.name not in exclude:

            comp_indices = slice(counter, counter+comp.n_species)
            c_total = np.sum(solution[..., comp_indices], axis=1)

            total_concentration += c_total

        counter += comp.n_species

    return total_concentration