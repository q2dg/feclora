import io
import struct
import uuid
import unittest
import binascii

from feclora.storage.gpt_binary import GPTBinaryError, inspect_gpt_binary


def make_gpt(sector_size=512, disk_sectors=100):
    entry_count = 128
    entry_size = 128
    array = bytearray(entry_count * entry_size)
    type_guid = uuid.UUID("0fc63daf-8483-4772-8e79-3d69d8477de4")
    unique_guid = uuid.UUID("11111111-2222-3333-4444-555555555555")
    first_usable = 2 + (len(array) + sector_size - 1) // sector_size
    array_sectors = (len(array) + sector_size - 1) // sector_size
    last_usable = disk_sectors - 2 - array_sectors
    struct.pack_into(
        "<16s16sQQQ", array, 0, type_guid.bytes_le, unique_guid.bytes_le,
        first_usable + 1, first_usable + 10, 0x1000000000000001,
    )
    array[56:56 + len("root".encode("utf-16le"))] = "root".encode("utf-16le")
    array_crc = binascii.crc32(array) & 0xFFFFFFFF
    disk_guid = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

    image = bytearray(sector_size * disk_sectors)
    image[510:512] = b"\\x55\\xaa"
    # One protective MBR entry: type EE, starts at LBA 1.
    image[446 + 4] = 0xEE
    struct.pack_into("<II", image, 446 + 8, 1, min(disk_sectors - 1, 0xFFFFFFFF))

    def write_header(lba, backup_lba, entries_lba):
        header = bytearray(sector_size)
        struct.pack_into(
            "<8sIIIIQQQQ16sQIII", header, 0,
            b"EFI PART", 0x00010000, 92, 0, 0, lba, backup_lba,
            first_usable, last_usable, disk_guid.bytes_le, entries_lba,
            entry_count, entry_size, array_crc,
        )
        crc = binascii.crc32(header[:92]) & 0xFFFFFFFF
        struct.pack_into("<I", header, 16, crc)
        image[lba * sector_size:(lba + 1) * sector_size] = header

    primary_entries_lba = 2
    backup_entries_lba = disk_sectors - 1 - array_sectors
    image[primary_entries_lba * sector_size:
          primary_entries_lba * sector_size + len(array)] = array
    image[backup_entries_lba * sector_size:
          backup_entries_lba * sector_size + len(array)] = array
    write_header(1, disk_sectors - 1, primary_entries_lba)
    write_header(disk_sectors - 1, 1, backup_entries_lba)
    return image, sector_size, disk_sectors


class BinaryGPTInspectionTests(unittest.TestCase):
    def inspect(self, image, sector_size, disk_sectors):
        return inspect_gpt_binary(
            io.BytesIO(image), sector_size=sector_size,
            disk_size_bytes=sector_size * disk_sectors,
        )

    def test_validates_both_gpt_copies_and_partition_entry(self):
        image, sector, sectors = make_gpt()
        result = self.inspect(image, sector, sectors)
        self.assertEqual(result["disk_guid"], "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        self.assertTrue(result["primary_backup_consistent"])
        self.assertEqual(len(result["partitions"]), 1)
        self.assertEqual(result["partitions"][0]["name"], "root")
        self.assertEqual(result["partitions"][0]["attributes"], 0x1000000000000001)

    def test_accepts_4kn_gpt_with_first_usable_lba_six(self):
        image, sector, sectors = make_gpt(sector_size=4096)
        result = self.inspect(image, sector, sectors)
        self.assertEqual(result["first_usable_lba"], 6)

    def test_rejects_primary_header_crc_corruption(self):
        image, sector, sectors = make_gpt()
        image[sector + 20] ^= 0x01
        with self.assertRaisesRegex(GPTBinaryError, "header CRC mismatch"):
            self.inspect(image, sector, sectors)

    def test_rejects_entry_array_crc_corruption(self):
        image, sector, sectors = make_gpt()
        image[2 * sector + 56] ^= 0x01
        backup_lba = sectors - 1 - 32
        image[backup_lba * sector + 56] ^= 0x01
        with self.assertRaisesRegex(GPTBinaryError, "entry array CRC mismatch"):
            self.inspect(image, sector, sectors)

    def test_rejects_primary_backup_array_disagreement(self):
        image, sector, sectors = make_gpt()
        backup_lba = sectors - 1 - 32
        image[backup_lba * sector + 56] ^= 0x01
        with self.assertRaisesRegex(GPTBinaryError, "arrays differ"):
            self.inspect(image, sector, sectors)

    def test_rejects_non_protective_or_hybrid_mbr(self):
        image, sector, sectors = make_gpt()
        image[446 + 4] = 0x07
        with self.assertRaisesRegex(GPTBinaryError, "protective MBR"):
            self.inspect(image, sector, sectors)

    def test_rejects_truncated_disk(self):
        image, sector, sectors = make_gpt()
        with self.assertRaisesRegex(GPTBinaryError, "truncated"):
            inspect_gpt_binary(
                io.BytesIO(image[:-sector]), sector_size=sector,
                disk_size_bytes=sector * sectors,
            )


if __name__ == "__main__":
    unittest.main()
