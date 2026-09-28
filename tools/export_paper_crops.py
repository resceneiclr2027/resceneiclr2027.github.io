"""Export pixel-preserving camera/BEV crops from manuscript case figures.

The crops are faithful views of the paper figures, not newly generated evidence.
They avoid browser-dependent absolute-position CSS cropping and strip metadata.
"""

from pathlib import Path

from PIL import Image


ASSETS = Path(__file__).resolve().parents[1] / 'assets'
CAMERA_FACTUAL = (64, 100, 1176, 726)
CAMERA_EDITED = (1221, 100, 2333, 726)
BEV_FACTUAL = (290, 830, 990, 1530)
BEV_EDITED = (1448, 830, 2148, 1530)

EXPORTS = (
    ('case-vehicle-removal.png', 'vehicle-factual-camera.png', CAMERA_FACTUAL),
    ('case-vehicle-removal.png', 'vehicle-edited-camera.png', CAMERA_EDITED),
    ('case-vehicle-removal.png', 'vehicle-factual-bev.png', BEV_FACTUAL),
    ('case-vehicle-removal.png', 'vehicle-edited-bev.png', BEV_EDITED),
    ('case-bicycle-removal.png', 'bicycle-removal-edited-bev.png', BEV_EDITED),
    ('case-bicycle-relocation.png', 'bicycle-relocation-edited-bev.png', BEV_EDITED),
)


def main():
    for source_name, target_name, box in EXPORTS:
        source = ASSETS / source_name
        target = ASSETS / target_name
        with Image.open(str(source)) as image:
            if image.size != (2400, 1740):
                raise ValueError('{} has unexpected manuscript export dimensions'.format(source_name))
            crop = image.crop(box).convert('RGB')
            crop.save(str(target), format='PNG', optimize=True)
        print('{}: {} x {}'.format(target_name, crop.width, crop.height))


if __name__ == '__main__':
    main()
