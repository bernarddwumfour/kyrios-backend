def get_all_prerequisites(course, visited=None) -> set:
    """
    Recursively fetches ALL prerequisites for a course.
    Handles circular references via visited set.

    e.g. Advanced React requires:
         → Intermediate React (which requires → Basic JavaScript)
         → TypeScript Basics

    Returns all of: {Intermediate React, Basic JavaScript, TypeScript Basics}
    """
    if visited is None:
        visited = set()

    if course.id in visited:
        return set()

    visited.add(course.id)
    all_prereqs = set()

    for prereq in course.prerequisites.prefetch_related("prerequisites").all():
        all_prereqs.add(prereq)
        # Recurse into this prerequisite's prerequisites
        all_prereqs.update(get_all_prerequisites(prereq, visited))

    return all_prereqs