CONFIG ?= configs/hey_mio.yaml
TEST_CONFIG ?= configs/hey_mio_test.yaml
MODEL ?= models/hey_mio.onnx

.PHONY: setup setup-test train train-test eval listen copy-model modal-setup modal-train modal-train-test modal-download

setup:
	livekit-wakeword setup --config $(CONFIG)

setup-test:
	livekit-wakeword setup --config $(TEST_CONFIG)

train:
	livekit-wakeword run $(CONFIG)

train-test:
	livekit-wakeword run $(TEST_CONFIG)

eval:
	livekit-wakeword eval $(CONFIG)

copy-model:
	cp output/hey_mio/hey_mio.onnx models/hey_mio.onnx

listen:
	python scripts/listen.py --model $(MODEL)

modal-setup:
	modal run modal_app.py --config $(CONFIG) --stage setup

modal-train:
	modal run --detach modal_app.py --config $(CONFIG) --stage run --gpu L40S

modal-train-test:
	modal run modal_app.py --config $(TEST_CONFIG) --stage run --gpu T4

modal-download:
	modal run modal_app.py --config $(CONFIG) --stage download
