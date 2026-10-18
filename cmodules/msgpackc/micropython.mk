# msgpackc for ports built with make (unix, stm32, rp2 with make, ...).
MSGPACKC_MOD_DIR := $(USERMOD_DIR)

SRC_USERMOD_C += $(MSGPACKC_MOD_DIR)/modmsgpackc.c
CFLAGS_USERMOD += -I$(MSGPACKC_MOD_DIR)
