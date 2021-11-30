from collections import defaultdict
import copy

import numpy as np
import matplotlib.pyplot as plt

from CADETProcess import CADETProcessError
from CADETProcess import plotting
from CADETProcess.processModel import ComponentSystem
from CADETProcess.processModel import MassActionLaw


# def check_charges(charges):
#     c_min = min(charges)
#     c_max = max(charges)
#     c_comparison = set(range(c_min, c_max+1))

#     if len(c_comparison) != len(charges) or set(charges) != c_comparison:
#         raise CADETProcessError("Charges are not valid")

# def order_by_charge(charges, k_eq, buffer):
#     indices = np.argsort(charges)

#     c, k, b = zip(*sorted(zip(charges, k_eq, buffer)))

#     return c, k, b


def preprocessing(reaction_system, buffer, pH, components):
    buffer_M = np.array([c*1e-3 for c in buffer])

    pH = np.asarray(pH, dtype=float)
    scalar_input = False
    if pH.ndim == 0:
        pH = pH[None]  # Makes x 1D
        scalar_input = True

    component_system = copy.deepcopy(reaction_system.component_system)

    indices = component_system.indices
    if components is not None:
        for comp in indices.copy():
            if comp not in components:
               indices.pop(comp)

    try:
        proton_index = indices.pop('H+')
    except ValueError:
        raise CADETProcessError("Could not find proton in component system")

    pKa = defaultdict(list)
    for r in reaction_system.reactions:
        reaction_indices = np.where(r.stoich)[0]
        for comp, i in indices.items():
            if not all(r_i in i + proton_index for r_i in reaction_indices):
                continue

            pKa[comp].append(-np.log10(r.k_eq*1e-3))

    c_acids_M = {
        comp: buffer_M[i].tolist()
        for comp, i in indices.items()
    }
    
    return pKa, c_acids_M, pH, indices, scalar_input
    

def c_species_nu(pKa, pH):
    """Compute normalized acid species concentration at given pH.

    Parameters
    ----------
    pKa : list
        List of pKa values.
    pH : float or list of floats.
        pH value

    Returns
    -------
    c_species_nu : np.array
        Normalized acid species concentration.
    """
    pKa = np.array([1.0] + pKa)
    k_eq = 10**(-pKa)
    n = len(k_eq)

    c_H = 10**(-pH)
    c_species_nu = np.zeros((n, len(pH)))

    for j in range(n):
        k = np.prod(k_eq[0:j+1])
        c_species_nu[j] = k*c_H**(n-j)

    return c_species_nu

def c_total_nu(pKa, pH):
    """Compute normalized total acid concentration at given pH.

    Parameters
    ----------
    pKa : list
        List of pKa values
    pH : float or list of floats.
        pH value

    Returns
    -------
    c_total_nu : np.array
        Normalized acid species concentration.
    """
    return sum(c_species_nu(pKa, pH))

def z_total_nu(pKa, pH):
    """Compute normalized total charge at given pH.

    Parameters
    ----------
    pKa : list
        List of pKa values
    pH : float or list of floats.
        pH value

    Returns
    -------
    z_total_nu : np.array
        Normalized acid species concentration.
    """
    c = c_species_nu(pKa, pH)

    return np.dot(np.arange(len(c)), c)

def eta(pKa, pH):
    """Compute degree of dissociation at given pH.

    Parameters
    ----------
    pKa : list
        List of pKa values
    pH : float or list of floats.
        pH value

    Returns
    -------
    eta : np.array
        Degree of dissociation.
    """
    return z_total_nu(pKa, pH)/c_total_nu(pKa, pH)

def charge_distribution(
        reaction_system,
        pH,
        components=None,
        ):
    """Calculate charge distribution at given pH.

    Parameters
    ----------
    reaction_system : ReactionModel
        Reaction system with deprotonation reactions.
    buffer : list
        Acid concentrations in mM.
    pH : float or array
        pH value of buffer.
    components : list, optional
        List of components to be considered in buffer capacity calculation.
        If None, all components are considerd.

    Returns
    -------
    buffer_capacity : np.array
        Buffer capacity in mM for individual acid components.
        To get overall buffer capacity, component capacities must be summed up.
    """
    buffer = reaction_system.n_comp * [1]
    pKa, c_acids_M, pH, indices, scalar_input = preprocessing(
        reaction_system, buffer, pH, components
    )
    
    z = np.zeros((len(pH), reaction_system.n_comp - 1))

    for comp, ind in indices.items():
        z_comp = alpha(pKa[comp], pH)
        for j, i in enumerate(ind):
            z[:,i] = z_comp[j,:]

    if scalar_input:
        return np.squeeze(z)

    return z

def cummulative_charge_distribution(
        reaction_system,
        pH,
        components=None,
        ):
    """Calculate cummulative charge at given pH.

    Parameters
    ----------
    reaction_system : ReactionModel
        Reaction system with deprotonation reactions.
    buffer : list
        Acid concentrations in mM.
    pH : float or array
        pH value of buffer.
    components : list, optional
        List of components to be considered in buffer capacity calculation.
        If None, all components are considerd.

    Returns
    -------
    buffer_capacity : np.array
        Buffer capacity in mM for individual acid components.
        To get overall buffer capacity, component capacities must be summed up.
    """
    buffer = reaction_system.n_comp * [1]
    pKa, c_acids_M, pH, indices, scalar_input = preprocessing(
        reaction_system, buffer, pH, components
    )
    
    z_cum = np.zeros((len(pH), len(indices)))
    
    for i, (comp, ind) in enumerate(indices.items()):
        charges = np.array(reaction_system.component_system.charges)[ind]
        max_charge = max(charges)
        z_cum[:,i] = max_charge - eta(pKa[comp], pH)

    if scalar_input:
        return np.squeeze(z_cum)

    return z_cum

def alpha(pKa, pH):
    """Compute degree of protolysis at given pH.

    Parameters
    ----------
    pKa : list
        List of pKa values
    pH : float or list of floats.
        pH value

    Returns
    -------
    alpha : np.array
        Degree of protolysis.
    """
    return c_species_nu(pKa, pH)/c_total_nu(pKa, pH)

def beta(c_acid, pKa, pH):
    """Compute buffer capacity of acid at given pH.

    Parameters
    ----------
    c_acid : TYPE
        DESCRIPTION.
    pKa : list
        List of pKa values
    pH : float or list of floats.
        pH value

    Returns
    -------
    beta : np.array
        Buffer capacity.
    """
    a = alpha(pKa, pH)
    beta = np.zeros(len(pH),)

    n = len(c_acid)
    for j in range(1, n):
        for i in range(0, j):
            print(f"j:{j}, i:{i}")
            beta += (j-i)**2 * a[j] * a[i]

    beta *= np.log(10) * sum(c_acid)

    return beta

def beta_water(pH):
    """Compute buffer capacity of water.

    Parameters
    ----------
    pH : float or list of floats.
        pH value

    Returns
    -------
    beta_water
        Buffer capacity of water.
    """
    c_H = 10**(-pH)
    return np.log(10)*(10**(-14)/c_H + c_H)

def buffer_capacity(
        reaction_system,
        buffer, pH,
        components=None,
        ):
    """Calculate buffer capacity at given buffer concentration and pH.

    Parameters
    ----------
    reaction_system : ReactionModel
        Reaction system with deprotonation reactions.
    buffer : list
        Acid concentrations in mM.
    pH : float or array
        pH value of buffer.
    components : list, optional
        List of components to be considered in buffer capacity calculation.
        If None, all components are considerd.

    Returns
    -------
    buffer_capacity : np.array
        Buffer capacity in mM for individual acid components.
        To get overall buffer capacity, component capacities must be summed up.
    """
    pKa, c_acids_M, pH, indices, scalar_input = preprocessing(
        reaction_system, buffer, pH, components
    )

    buffer_capacity = np.zeros((len(pH), len(c_acids_M)+1))

    for i, comp in enumerate(indices):
        buffer_capacity[:,i] = beta(c_acids_M[comp], pKa[comp], pH)

    buffer_capacity[:,-1] = beta_water(pH)

    buffer_capacity *= 1e3
    if scalar_input:
        return np.squeeze(buffer_capacity)

    return buffer_capacity

def ionic_strength(component_system, buffer):
    """Compute ionic strength.

    Parameters
    ----------
    buffer : list
        Buffer concentrations in mM.
    component_system : ComponentSystem
        Component system; must contain charges.

    Returns
    -------
    i: np.array
        Ionic strength of buffer

    """
    if not isinstance(component_system, ComponentSystem):
        raise TypeError("Expected ComponentSystem")
    if len(buffer) != component_system.n_comp:
        raise CADETProcessError("Number of components does not match")

    buffer = np.asarray(buffer)
    z = np.asarray(component_system.charges)
    return 1/2 * np.sum(buffer*z**2)

@plotting.save_fig
def plot_buffer_capacity(reaction_system, buffer, pH=None):
    """Plot buffer capacity of reaction system over pH at given concentration.

    Parameters
    ----------
    reaction_system : MassActionLaw
        Reaction system with stoichiometric coefficients and reaction rates.
    buffer : list
        Buffer concentration in mM.
    pH : np.array, optional
        Range of pH to be plotted.

    Returns
    -------
    ax : Axes
        The new axes.
    """
    if pH is None:
        pH = np.linspace(0,14,101)

    b = buffer_capacity(reaction_system, buffer, pH)
    b_total = np.sum(b, axis=1)

    fig, ax = plotting.setup_figure()
    ax.plot(pH, b_total, 'k*', label='Total buffer capacity')
    for i in range(reaction_system.component_system.n_components - 1):
        ax.plot(pH, b[:,i], label=reaction_system.component_system.components[i].name)
    ax.plot(pH, b[:,-1], label='Water')

    layout = plotting.Layout()
    layout.x_label = '$pH$'
    layout.y_label = '$buffer capacity~/~mM$'
    layout.ylim = (0, 1.1*np.max(b_total))

    plotting.set_layout(fig, ax, layout)
    
    return ax

@plotting.save_fig
def plot_charge_distribution(reaction_system, pH=None, plot_cumulative=False):
    """Plot charge distribution of components over pH.

    Parameters
    ----------
    reaction_system : MassActionLaw
        Reaction system with stoichiometric coefficients and reaction rates.
    buffer : list
        Buffer concentration in mM.
    pH : np.array, optional
        Range of pH to be plotted.

    Returns
    -------
    ax : Axes
        The new axes.
    """
    if pH is None:
        pH = np.linspace(0,14,101)

    if plot_cumulative:
        c = cummulative_charge_distribution(reaction_system, pH)
    else:
        c = charge_distribution(reaction_system, pH)

    fig, ax = plotting.setup_figure()
    if plot_cumulative:
        labels = reaction_system.component_system.names
    else:
        labels = reaction_system.component_system.labels

    for i, l in zip(c.T, labels): 
        ax.plot(pH, i, label=l)

    layout = plotting.Layout()
    layout.x_label = '$pH$'
    layout.y_label = '$cumulative charge$'
    layout.ylim = (1.1*np.min(c), 1.1*np.max(c))

    plotting.set_layout(fig, ax, layout)
    
    return ax