from copy import deepcopy
import numpy as np

from CADETProcess import CADETProcessError

from CADETProcess.dataStructure import StructMeta
from CADETProcess.dataStructure import Integer, UnsignedInteger, UnsignedFloat

from CADETProcess.processModel import UnitBaseClass, FlowSheet, Process
from CADETProcess.processModel import TubularReactor, Cstr


class CarouselBuilder(metaclass=StructMeta):
    switch_time = UnsignedFloat()

    def __init__(self, component_system, name):
        self.component_system = component_system
        self.name = name
        self._flow_sheet = FlowSheet(component_system, name)
        self._column = None

    @property
    def flow_sheet(self):
        return self._flow_sheet

    @property
    def column(self):
        return self._column

    @column.setter
    def column(self, column):
        if not isinstance(column, TubularReactor):
            raise TypeError
        if self.component_system is not column.component_system:
            raise CADETProcessError('Number of components does not match.')
        self._column = column


    def add_unit(self, unit):
        """Wrapper around auxiliary flow_sheet
        """
        self.flow_sheet.add_unit(unit)

    def add_connection(self, origin, destination):
        """Wrapper around auxiliary flow_sheet
        """
        self.flow_sheet.add_connection(origin, destination)

    def set_output_state(self, unit, state):
        """Wrapper around auxiliary flow_sheet
        """
        self.flow_sheet.set_output_state(unit, state)

    @property
    def zones(self):
        """list: list of all zones in the carousel system.
        """
        return [
            unit for unit in self.flow_sheet.units if isinstance(unit, ZoneBaseClass)
        ]

    @property
    def zones_dict(self):
        """dict: Zone names and objects.
        """
        return {zone.name: zone for zone in self.zones}

    @property
    def n_zones(self):
        """int: Number of zones in the Carousel System
        """
        return len(self.zones)

    @property
    def n_columns(self):
        """int: Number of columns in the Carousel System
        """
        return sum([zone.n_columns for zone in self.zones])

    def build_flow_sheet(self):
        flow_sheet = FlowSheet(self.component_system, self.name)
        self.add_units(flow_sheet)
        self.add_inter_zone_connections(flow_sheet)
        self.add_intra_zone_connections(flow_sheet)

        return flow_sheet

    def add_units(self, flow_sheet):
        col_index = 0
        for unit in self.flow_sheet.units:
            if not isinstance(unit, ZoneBaseClass):
                flow_sheet.add_unit(unit)
            else:
                flow_sheet.add_unit(unit.inlet_unit)
                flow_sheet.add_unit(unit.outlet_unit)
                for i_col in range(unit.n_columns):
                    col = deepcopy(self.column)
                    col.component_system = self.component_system
                    col.name = f'column_{col_index}'
                    if unit.initial_state is not None:
                        col.initial_state = unit.initial_state[i_col]
                    flow_sheet.add_unit(col)
                    col_index += 1

    def add_inter_zone_connections(self, flow_sheet):
        for unit, connections in self.flow_sheet.connections.items():
            if isinstance(unit, ZoneBaseClass):
                origin = unit.outlet_unit
            else:
                origin = unit

            for destination in connections.destinations:
                if isinstance(destination, ZoneBaseClass):
                    destination = destination.inlet_unit

                flow_sheet.add_connection(origin, destination)

        flow_rates = self.flow_sheet.get_flow_rates()
        for zone in self.zones:
            output_state = self.flow_sheet.output_states[zone]
            flow_sheet.set_output_state(zone.outlet_unit, output_state)
            flow_sheet[zone.inlet_unit.name].flow_rate = flow_rates[zone.name].total
            flow_sheet[zone.outlet_unit.name].flow_rate = flow_rates[zone.name].total

    def add_intra_zone_connections(self, flow_sheet):
        for zone in self.zones:
            for col_index in range(self.n_columns):
                col = flow_sheet[f'column_{col_index}']
                flow_sheet.add_connection(zone.inlet_unit, col)
                col = flow_sheet[f'column_{col_index}']
                flow_sheet.add_connection(col, zone.outlet_unit)

        for col_index in range(self.n_columns):
            col_orig = flow_sheet[f'column_{col_index}']
            if col_index < self.n_columns - 1:
                col_dest = flow_sheet[f'column_{col_index + 1}']
            else:
                col_dest = flow_sheet[f'column_{0}']
            flow_sheet.add_connection(col_orig, col_dest)


    def build_process(self):
        flow_sheet = self.build_flow_sheet()
        process = Process(flow_sheet, self.name)

        self.add_events(process)

        return process

    def add_events(self, process):
        process.cycle_time = self.n_columns * self.switch_time
        process.add_duration('switch_time', self.switch_time)

        for carousel_state in range(self.n_columns):
            position_counter = 0
            for i_zone, zone in enumerate(self.zones):
                col_indices = np.arange(zone.n_columns)
                col_indices += position_counter
                col_indices = self.unit_index(col_indices, carousel_state)

                if isinstance(zone, SerialZone):
                    evt = process.add_event(
                        f'{zone.name}_{carousel_state}',
                        f'flow_sheet.output_states.{zone.inlet_unit}',
                        col_indices[0]
                    )
                    process.add_event_dependency(
                        evt.name, 'switch_time', [carousel_state]
                    )
                    for i, col in enumerate(col_indices):
                        if i < (zone.n_columns - 1):
                            evt = process.add_event(
                                f'column_{col}_{carousel_state}',
                                f'flow_sheet.output_states.column_{col}',
                                self.n_zones
                            )
                        else:
                            evt = process.add_event(
                                f'column_{col}_{carousel_state}',
                                f'flow_sheet.output_states.column_{col}',
                                i_zone
                            )
                        process.add_event_dependency(
                            evt.name, 'switch_time', [carousel_state]
                        )
                elif isinstance(zone, ParallelZone):
                    output_state = self.n_columns * [0]
                    for col in col_indices:
                        output_state[col] = 1/zone.n_columns

                    evt = process.add_event(
                            f'{zone.name}_{carousel_state}',
                            f'flow_sheet.output_states.{zone.inlet_unit}',
                            output_state
                    )
                    process.add_event_dependency(
                            evt.name, 'switch_time', [carousel_state]
                    )

                    for col in col_indices:
                        evt = process.add_event(
                            f'column_{col}_{carousel_state}',
                            f'flow_sheet.output_states.column_{col}',
                            i_zone
                        )
                        process.add_event_dependency(
                            evt.name, 'switch_time', [carousel_state]
                        )

                for i, col in enumerate(col_indices):
                    evt = process.add_event(
                        f'column_{col}_{carousel_state}_velocity',
                        f'flow_sheet.column_{col}.flow_direction',
                        zone.flow_direction
                    )
                    process.add_event_dependency(
                        evt.name, 'switch_time', [carousel_state]
                    )

                position_counter += zone.n_columns


    def unit_index(self, carousel_position, carousel_state):
        """Return unit index of column at given carousel position and state.

        Parameters
        ----------
        carousel_position : int
            Column position index (e.g. wash position, elute position).
        carousel_state : int
            Curent state of the carousel system.
        n_columns : int
            Total number of columns in system.
        """
        return (carousel_position + carousel_state) % self.n_columns


class ZoneBaseClass(UnitBaseClass):
    n_columns = UnsignedInteger()
    flow_direction = Integer(default=1)
    _valve_dead_volume = 1e-6

    def __init__(
            self,
            component_system, name, n_columns=1,
            flow_direction=1, initial_state=None, 
            *args, **kwargs
        ):
        self.n_columns = n_columns
        self.flow_direction = flow_direction
        self.initial_state = initial_state

        self._inlet_unit = Cstr(component_system, f'{name}_inlet')

        self._inlet_unit.V = self._valve_dead_volume
        self._outlet_unit = Cstr(component_system, f'{name}_outlet')
        self._outlet_unit.V = self._valve_dead_volume

        super().__init__(component_system, name, *args, **kwargs)

    @property
    def initial_state(self):
        return self._initial_state

    @initial_state.setter
    def initial_state(self, initial_state):
        if initial_state is None:
            self._initial_state = initial_state
            return

        if not isinstance(initial_state, list):
            initial_state = self.n_columns * [initial_state]

        if len(initial_state) != self.n_columns:
            raise CADETProcessError(f"Expected size {self.n_columns}")

        self._initial_state = initial_state

    @property
    def inlet_unit(self):
        return self._inlet_unit

    @property
    def outlet_unit(self):
        return self._outlet_unit

class SerialZone(ZoneBaseClass):
    pass

class ParallelZone(ZoneBaseClass):
    pass
