"""Adapters connect the factory's local source-of-truth to the outside world.

``github`` mirrors a work item's state onto a GitHub issue's labels (so the
conveyor is visible in GitHub and the cloud-autonomy workflows can trigger off
label changes) and lists labeled issues for intake. Local JSON stays the
source of truth; adapters are optional.
"""
