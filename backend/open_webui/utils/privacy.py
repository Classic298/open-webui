def is_private_to_other_user(item, current_user_id):
    """
    Check if an item is private to another user (not accessible to admin).
    
    An item is considered private to another user if:
    1. It has empty access_control (no sharing permissions = set to private)
    2. AND it belongs to a different user than the current admin
    
    Args:
        item: Item object with access_control and user_id attributes
        current_user_id: ID of the current user (admin)
    
    Returns:
        bool: True if item is private to another user, False otherwise
    """
    return (
        item.access_control == {} and 
        item.user_id != current_user_id
    )


def filter_private_items(items, current_user, respect_privacy=False):
    """
    Filter out private items from other users if admin privacy is enabled.
    If admin privacy is enabled, admin will only see his own items or items shared with him (group permissions).
    Private (non-shared) items will be hidden from the admin in this case.
    
    Args:
        items: List of items to filter
        current_user: Current user object
        respect_privacy: Whether to filter private items (from config)
    
    Returns:
        Filtered list of items
    """
    if current_user.role != "admin" or not respect_privacy:
        return items
    
    return [
        item for item in items 
        if not is_private_to_other_user(item, current_user.id)
    ]
