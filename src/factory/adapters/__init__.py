"""Adapters connect the factory's local source-of-truth to the outside world.

``github`` mirrors a work item's state onto a GitHub issue's labels and posts
review packets as comments, so the conveyor is visible in GitHub and the
cloud-autonomy workflows can trigger off label changes. Local JSON stays the
source of truth; adapters are optional.
"""
