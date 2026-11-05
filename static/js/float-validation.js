/**
 * Float Validation Utility
 * Automatically handles validation for inputs with class .validate-float
 */
(function() {
    // Regex: empty string OR optional minus, digits, optional dot and decimal digits
    const floatRegex = /^$|^-?\d+(\.\d+)?$/;

    function validateInput(input) {
        // Replace comma with dot automatically
        let val = input.value.trim().replace(',', '.');
        input.value = val;

        const isValid = floatRegex.test(val);
        if (!isValid) {
            input.classList.add('is-invalid');
        } else {
            input.classList.remove('is-invalid');
        }
        return isValid;
    }

    function updateSubmitButton(form) {
        // Find submit button in this form. Try by ID first, then by type
        let submitBtn = form.querySelector('#submit-btn') || form.querySelector('button[type="submit"]');
        if (submitBtn) {
            const hasErrors = form.querySelectorAll('.validate-float.is-invalid').length > 0;
            submitBtn.disabled = hasErrors;
        }
    }

    // Use event delegation for change and blur
    document.addEventListener('change', function(e) {
        if (e.target.classList.contains('validate-float')) {
            validateInput(e.target);
            const form = e.target.closest('form');
            if (form) updateSubmitButton(form);
        }
    }, true);

    document.addEventListener('blur', function(e) {
        if (e.target.classList.contains('validate-float')) {
            validateInput(e.target);
            const form = e.target.closest('form');
            if (form) updateSubmitButton(form);
        }
    }, true);

    // Form submit validation
    document.addEventListener('submit', function(e) {
        const form = e.target;
        const inputs = form.querySelectorAll('.validate-float');
        if (inputs.length > 0) {
            let allValid = true;
            inputs.forEach(input => {
                if (!validateInput(input)) {
                    allValid = false;
                }
            });
            if (!allValid) {
                e.preventDefault();
                updateSubmitButton(form);
                
                // Focus first invalid input
                const firstInvalid = form.querySelector('.validate-float.is-invalid');
                if (firstInvalid) firstInvalid.focus();
            }
        }
    });
})();
