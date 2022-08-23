### MFSim -> OpenDrop translator and execution engine

This takes in a *.mfprog file, which consisted of line-separated activation records for controlling a DMFB, translates them to OpenDrop coordinates, and serially sends instructions to the OpenDrop for execution.
Each line is formed with a time step and a space-separated list of electrode coordinates to activate, i.e.,:

`0: (0, 1) (10, 2)`
signifies that at time-step 0, there are two electrodes that should be active.

This currently only supports .mfprog files, which essentially corresponds to execution of a single DAG (i.e., straight-line code).  To support more complex experiments, we'd need to interpret a CFG.

As MFSim abstracts I/O reservoirs, it generates electrode mappings where `(0,0)` indicates the top left corner of the electrode array.

OpenDrop utilizes 4 TCC I/O reservoirs (two on the left and right sides of the chip).
The electrode mapping for activating the TCC electrodes shifts the primary grid of a 2d bitmap to the right by one, and utilizes the first column for controlling the two left reservoirs. The right reservoirs are controlled using an additional column to the right of the (now right-shifted) grid.

Hence, a 16-column OpenDrop requires at least 18 columns to completely control;  we send this 18-column electrode matrix to the OpenDrop, followed by a 14-column matrix of control data (the interpreter on the OpenDrop requires control data in order to set e.g., magnets, thermoelectric modules, etc.).