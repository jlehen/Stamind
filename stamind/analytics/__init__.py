"""Training maths that reads no database and talks to no service.

Every module here takes rows and returns numbers or text: the load model, the
fitness/fatigue (PMC) series, adherence, the intensity distribution, the progress
timeline. The rows are fetched by whoever calls in.

Nothing is re-exported from here. A caller names the module it wants
(`from stamind.analytics.load import activity_load`), so importing the zone model does
not drag the PMC series in behind it.
"""
