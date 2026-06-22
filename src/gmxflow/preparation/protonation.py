def histidine_form_for_ph(ph: float, force_field_name: str = "") -> str:
    forms = ("HIP", "HID", "HIE")
    if "charmm" in force_field_name.lower():
        forms = ("HSP", "HSD", "HSE")
    if ph < 6.5:
        return forms[0]
    if ph < 8.0:
        return forms[1]
    return forms[2]
