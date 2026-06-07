# Accessibility Review Guidance

AirReview guidance:

- Review UI changes for keyboard access, focus management, labels, semantic roles, contrast-sensitive states, and screen-reader-visible names.
- Interactive elements should be reachable by keyboard and should not rely only on color, hover, or pointer interaction.
- Buttons, links, form controls, dialogs, menus, and alerts should use semantic HTML or correct ARIA patterns.
- Avoid accessibility findings when the changed code is not UI-related or when the issue is not introduced or aggravated by the branch.
- A useful accessibility comment should name the affected interaction and propose a concrete fix, such as adding a label, using a button instead of a div, or restoring focus after a dialog closes.

