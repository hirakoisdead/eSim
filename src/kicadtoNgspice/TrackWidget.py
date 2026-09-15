class TrackWidget:
    """
    - This Class tracks the dynamically created widgets of the
      KicadtoNgSpice Window.
    - Tracks using dictionaries and lists ==>
        - Sources
        - Parameters
        - References
        - Model Details
        - ... etc
    - All state is per-instance. One TrackWidget is created per conversion
      run by the converter window and injected into every tab and into
      Convert, so two converter windows can never clobber each other's data
      bus. (Historically this state was class-level and shared, and an
      external single-instance guard held it together.)
    - __init__ starts every field empty, which is the fresh state a new
      conversion run needs; there is no separate reset step.
    """

    def __init__(self):
        # Track widget list for Source details
        self.sourcelisttrack = {"ITEMS": "None"}
        self.source_entry_var = {"ITEMS": "None"}

        # Track widget for analysis inserter details
        self.AC_entry_var = {"ITEMS": "None"}
        self.AC_Parameter = {"ITEMS": "None"}
        self.DC_entry_var = {"ITEMS": "None"}
        self.DC_Parameter = {"ITEMS": "None"}
        self.TRAN_entry_var = {"ITEMS": "None"}
        self.TRAN_Parameter = {"ITEMS": "None"}
        self.set_CheckBox = {"ITEMS": "None"}
        self.AC_type = {"ITEMS": "None"}
        self.op_check = []

        # Track widget for Model detail
        self.modelTrack = []
        self.microcontrollerTrack = []
        self.model_entry_var = {}
        self.microcontroller_var = {}

        # Track Widget for Device Model detail
        self.deviceModelTrack = {}

        # Track Widget for Subcircuits where directory has been selected
        self.subcircuitTrack = {}
        # Track subcircuits which are specified in .cir file
        self.subcircuitList = {}
