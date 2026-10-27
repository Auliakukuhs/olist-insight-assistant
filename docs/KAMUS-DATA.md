# Kamus data OLIST

Dibangun otomatis oleh `scripts/kamus_data.py` dari `data/olist.db`. Agent SQL dan endpoint analytics hanya membaca view di bawah, tidak membaca tabel mentah.

## Jebakan data

Hal yang perlu diingat saat membaca angka, menulis prompt agent, atau menjawab pertanyaan penguji.

| Jebakan | Angka | Akibat dan penanganan |
|---|---|---|
| Review tanpa teks | 58,7 persen dari 99.224 review (judul kosong 88,3 persen) | Qdrant hanya memuat review yang punya judul atau teks (`rag/documents.py`). Skor semua review tetap dipakai SQL |
| Produk tanpa kategori | 610 produk, 1.603 item | Diberi kategori `unknown` supaya tidak hilang dari total |
| Data historis | Pesanan 4 September 2016 sampai 17 Oktober 2018 | Bukan harga, stok, atau seller saat ini. Ditolak bila ditanya "sekarang" |
| Pesanan belum tiba | 2.965 pesanan tanpa tanggal tiba | `terlambat` dan `hari_kirim` kosong, tidak dihitung sebagai tepat waktu |
| Pesanan batal | 549 item `canceled` dan `unavailable` (97.242,96 BRL) | Tidak masuk penjualan. Pakai `v_item_terjual` untuk penjualan |
| Join pembayaran | Join langsung item dengan pembayaran menaikkan total dari 16,0 juta menjadi 20,3 juta BRL | Pembayaran dan review diringkas per pesanan dulu |
| Pesanan tanpa review | 768 pesanan | `skor` kosong |
| Kategori dan seller kecil | 11 dari 74 kategori di bawah 30 pesanan, 3 di bawah 10 | Peringkat rasio (skor, persen terlambat) memakai minimal 30 pesanan, ditegakkan di kode agent SQL (`MIN_ORDER`) |
| Nama dan kontak | Tidak ada di data | Pertanyaan nama, alamat, atau kontak orang ditolak |

## `v_item_penjualan`

Satu baris per item pesanan, semua status. 112.650 baris.

| Kolom | Tipe | Satuan | Keterangan | Kosong | Contoh |
|---|---|---|---|---|---|
| `order_id` | teks | - | ID pesanan, 32 karakter heksadesimal | 0% | `00010242fe8c...`, `00018f77f2f0...`, `000229ec3982...` |
| `order_item_id` | bilangan bulat | - | Urutan item di dalam satu pesanan, mulai 1 | 0% | `1`, `2`, `3` |
| `product_id` | teks | - | ID produk. Data tidak memuat nama atau foto produk | 0% | `4244733e06e7...`, `e5f2d52b8021...`, `c777355d18b7...` |
| `seller_id` | teks | - | ID seller. Data internal, hanya admin yang melihat seller lain | 0% | `0015a82c2db0...`, `001cca7ae9ae...`, `001e6ad469a9...` |
| `kategori` | teks | - | Kategori produk dalam bahasa Inggris. Produk tanpa kategori diberi `unknown` | 0% | `cool_stuff`, `pet_shop`, `furniture_decor` |
| `harga_brl` | desimal | BRL | Harga item, tanpa ongkir | 0% | `58.9`, `239.9`, `199` |
| `ongkir_brl` | desimal | BRL | Ongkos kirim item | 0% | `13.29`, `19.93`, `17.87` |
| `tanggal_beli` | teks | waktu lokal Brasil | Waktu pesanan dibuat, `YYYY-MM-DD HH:MM:SS` | 0% | `2017-10-02 10:56:33`, `2018-07-24 20:41:37`, `2018-08-08 08:38:49` |
| `status_order` | teks | - | Status pesanan, misalnya `delivered`, `shipped`, `canceled` | 0% | `delivered`, `invoiced`, `shipped` |
| `kota_seller` | teks | - | Kota seller, huruf kecil tanpa aksen | 0% | `volta redonda`, `sao paulo`, `borda da mata` |
| `negara_bagian_seller` | teks | - | Kode negara bagian seller, dua huruf | 0% | `SP`, `MG`, `PR` |
| `kota_pembeli` | teks | - | Kota pembeli, huruf kecil tanpa aksen | 0% | `campos dos g...`, `santa fe do sul`, `para de minas` |
| `negara_bagian_pembeli` | teks | - | Kode negara bagian pembeli, dua huruf | 0% | `RJ`, `SP`, `MG` |

## `v_item_terjual`

Satu baris per item pesanan tanpa status `canceled` dan `unavailable`. 112.101 baris.

| Kolom | Tipe | Satuan | Keterangan | Kosong | Contoh |
|---|---|---|---|---|---|
| `order_id` | teks | - | ID pesanan, 32 karakter heksadesimal | 0% | `00010242fe8c...`, `00018f77f2f0...`, `000229ec3982...` |
| `order_item_id` | bilangan bulat | - | Urutan item di dalam satu pesanan, mulai 1 | 0% | `1`, `2`, `3` |
| `product_id` | teks | - | ID produk. Data tidak memuat nama atau foto produk | 0% | `4244733e06e7...`, `e5f2d52b8021...`, `c777355d18b7...` |
| `seller_id` | teks | - | ID seller. Data internal, hanya admin yang melihat seller lain | 0% | `0015a82c2db0...`, `001cca7ae9ae...`, `002100f778ce...` |
| `kategori` | teks | - | Kategori produk dalam bahasa Inggris. Produk tanpa kategori diberi `unknown` | 0% | `housewares`, `perfumery`, `auto` |
| `harga_brl` | desimal | BRL | Harga item, tanpa ongkir | 0% | `58.9`, `239.9`, `199` |
| `ongkir_brl` | desimal | BRL | Ongkos kirim item | 0% | `13.29`, `19.93`, `17.87` |
| `tanggal_beli` | teks | waktu lokal Brasil | Waktu pesanan dibuat, `YYYY-MM-DD HH:MM:SS` | 0% | `2017-10-02 10:56:33`, `2018-07-24 20:41:37`, `2018-08-08 08:38:49` |
| `status_order` | teks | - | Status pesanan, misalnya `delivered`, `shipped`, `canceled` | 0% | `delivered`, `invoiced`, `shipped` |
| `kota_seller` | teks | - | Kota seller, huruf kecil tanpa aksen | 0% | `maua`, `belo horizonte`, `guariba` |
| `negara_bagian_seller` | teks | - | Kode negara bagian seller, dua huruf | 0% | `SP`, `MG`, `ES` |
| `kota_pembeli` | teks | - | Kota pembeli, huruf kecil tanpa aksen | 0% | `sao paulo`, `barreiras`, `vianopolis` |
| `negara_bagian_pembeli` | teks | - | Kode negara bagian pembeli, dua huruf | 0% | `SP`, `BA`, `GO` |

## `v_order`

Satu baris per pesanan. 99.441 baris.

| Kolom | Tipe | Satuan | Keterangan | Kosong | Contoh |
|---|---|---|---|---|---|
| `order_id` | teks | - | ID pesanan, 32 karakter heksadesimal | 0% | `00010242fe8c...`, `00018f77f2f0...`, `000229ec3982...` |
| `status_order` | teks | - | Status pesanan, misalnya `delivered`, `shipped`, `canceled` | 0% | `delivered`, `invoiced`, `shipped` |
| `tanggal_beli` | teks | waktu lokal Brasil | Waktu pesanan dibuat, `YYYY-MM-DD HH:MM:SS` | 0% | `2017-10-02 10:56:33`, `2018-07-24 20:41:37`, `2018-08-08 08:38:49` |
| `terlambat` | bilangan bulat | 0 atau 1 | 1 bila tiba sesudah tanggal estimasi. Kosong bila belum tiba | 3% | `0`, `1` |
| `hari_kirim` | desimal | hari | Lama dari pesan sampai tiba di pembeli. Kosong bila belum tiba | 3% | `8.44`, `13.78`, `9.39` |
| `skor` | desimal | 1 sampai 5 | Rata-rata skor review pesanan. Kosong bila tanpa review | 0,8% | `4`, `5`, `2` |

## `v_pembayaran_per_order`

Satu baris per pesanan yang punya data pembayaran. 99.440 baris.

| Kolom | Tipe | Satuan | Keterangan | Kosong | Contoh |
|---|---|---|---|---|---|
| `order_id` | teks | - | ID pesanan, 32 karakter heksadesimal | 0% | `00010242fe8c...`, `00018f77f2f0...`, `000229ec3982...` |
| `jumlah_pembayaran` | bilangan bulat | transaksi | Jumlah transaksi pembayaran untuk pesanan | 0% | `1`, `2`, `6` |
| `total_bayar_brl` | desimal | BRL | Total dibayar pembeli, termasuk ongkir | 0% | `72.19`, `259.83`, `216.87` |
| `cicilan_maks` | bilangan bulat | kali | Jumlah cicilan terbesar di pesanan | 0% | `2`, `3`, `5` |
| `metode` | teks | - | Metode pembayaran utama, misalnya `credit_card`, `boleto` | 0% | `credit_card`, `boleto`, `voucher,credit_card` |

## `v_review_per_order`

Satu baris per pesanan yang punya review. 98.673 baris.

| Kolom | Tipe | Satuan | Keterangan | Kosong | Contoh |
|---|---|---|---|---|---|
| `order_id` | teks | - | ID pesanan, 32 karakter heksadesimal | 0% | `00010242fe8c...`, `00018f77f2f0...`, `000229ec3982...` |
| `skor` | desimal | 1 sampai 5 | Rata-rata skor review pesanan. Kosong bila tanpa review | 0% | `5`, `4`, `1` |
| `jumlah_review` | bilangan bulat | review | Jumlah review untuk pesanan ini | 0% | `1`, `2`, `3` |

## `v_pasar`

Satu baris per item terjual tanpa `seller_id`, untuk customer dan seller. 112.101 baris.

| Kolom | Tipe | Satuan | Keterangan | Kosong | Contoh |
|---|---|---|---|---|---|
| `order_id` | teks | - | ID pesanan, 32 karakter heksadesimal | 0% | `e481f51cbdc5...`, `53cdb2fc8bc7...`, `47770eb9100c...` |
| `product_id` | teks | - | ID produk. Data tidak memuat nama atau foto produk | 0% | `87285b348845...`, `595fac2a385a...`, `aa4383b373c6...` |
| `kategori` | teks | - | Kategori produk dalam bahasa Inggris. Produk tanpa kategori diberi `unknown` | 0% | `agro_industr...`, `air_conditioning`, `art` |
| `harga_brl` | desimal | BRL | Harga item, tanpa ongkir | 0% | `29.99`, `118.7`, `159.9` |
| `ongkir_brl` | desimal | BRL | Ongkos kirim item | 0% | `8.72`, `22.76`, `19.22` |
| `tanggal_beli` | teks | waktu lokal Brasil | Waktu pesanan dibuat, `YYYY-MM-DD HH:MM:SS` | 0% | `2017-10-02 10:56:33`, `2018-07-24 20:41:37`, `2018-08-08 08:38:49` |
| `kota_seller` | teks | - | Kota seller, huruf kecil tanpa aksen | 0% | `maua`, `belo horizonte`, `guariba` |
| `negara_bagian_seller` | teks | - | Kode negara bagian seller, dua huruf | 0% | `SP`, `MG`, `ES` |
| `kota_pembeli` | teks | - | Kota pembeli, huruf kecil tanpa aksen | 0% | `sao paulo`, `barreiras`, `vianopolis` |
| `negara_bagian_pembeli` | teks | - | Kode negara bagian pembeli, dua huruf | 0% | `SP`, `BA`, `GO` |
| `terlambat` | bilangan bulat | 0 atau 1 | 1 bila tiba sesudah tanggal estimasi. Kosong bila belum tiba | 1,7% | `0`, `1` |
| `hari_kirim` | desimal | hari | Lama dari pesan sampai tiba di pembeli. Kosong bila belum tiba | 1,7% | `8.4`, `13.8`, `9.4` |
| `skor_ulasan` | desimal | 1 sampai 5 | Rata-rata skor review pesanan. Kosong bila tanpa review | 0,8% | `4`, `5`, `2` |

## `v_ringkasan_kategori`

Satu baris per kategori. 74 baris.

| Kolom | Tipe | Satuan | Keterangan | Kosong | Contoh |
|---|---|---|---|---|---|
| `kategori` | teks | - | Kategori produk dalam bahasa Inggris. Produk tanpa kategori diberi `unknown` | 0% | `agro_industr...`, `air_conditioning`, `art` |
| `jumlah_order` | bilangan bulat | pesanan | Jumlah pesanan unik | 0% | `182`, `251`, `201` |
| `total_penjualan_brl` | desimal | BRL | Jumlah harga item terjual, tanpa ongkir | 0% | `72530.47`, `54723.16`, `24167.64` |
| `rata_harga_brl` | desimal | BRL | Rata-rata harga item | 0% | `342.12`, `185.5`, `116.19` |
| `rata_ongkir_brl` | desimal | BRL | Rata-rata ongkir item | 0% | `27.56`, `22.76`, `19.37` |
| `rata_skor` | desimal | 1 sampai 5 | Rata-rata skor review pesanan | 0% | `4.02`, `4.05`, `4.04` |
| `persen_terlambat` | desimal | persen | Persen pesanan tiba sesudah estimasi, dari yang sudah tiba | 0% | `4`, `4.1`, `6.2` |

## `v_ringkasan_seller`

Satu baris per seller. 3.095 baris.

| Kolom | Tipe | Satuan | Keterangan | Kosong | Contoh |
|---|---|---|---|---|---|
| `seller_id` | teks | - | ID seller. Data internal, hanya admin yang melihat seller lain | 0% | `0015a82c2db0...`, `001cca7ae9ae...`, `001e6ad469a9...` |
| `kota` | teks | - | Kota seller | 0% | `campinas`, `mogi guacu`, `rio de janeiro` |
| `negara_bagian` | teks | - | Kode negara bagian seller | 0% | `SP`, `RJ`, `PE` |
| `kategori_utama` | teks | - | Kategori dengan penjualan terbesar milik seller | 1,4% | `sports_leisure`, `luggage_accessories`, `baby` |
| `jumlah_order` | bilangan bulat | pesanan | Jumlah pesanan unik | 0% | `3`, `39`, `1` |
| `total_penjualan_brl` | desimal, bilangan bulat | BRL | Jumlah harga item terjual, tanpa ongkir | 0% | `218.7`, `11413.17`, `158` |
| `rata_skor` | desimal | 1 sampai 5 | Rata-rata skor review pesanan | 1,5% | `3`, `4.64`, `5` |
| `rata_hari_kirim` | desimal | hari | Rata-rata lama kirim pesanan yang sudah tiba | 4% | `13`, `9.2`, `4` |
| `persen_terlambat` | desimal | persen | Persen pesanan tiba sesudah estimasi, dari yang sudah tiba | 4% | `33.3`, `2.6`, `0` |
