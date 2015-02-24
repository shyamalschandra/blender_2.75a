/*
 * Copyright 2013, Blender Foundation.
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public License
 * as published by the Free Software Foundation; either version 2
 * of the License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software Foundation,
 * Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
 */

#include "alembic.h"
#include "abc_dynamicpaint.h"
#include "util_path.h"

extern "C" {
#include "DNA_object_types.h"
#include "DNA_dynamicpaint_types.h"
}

#include "PTC_api.h"

namespace PTC {

using namespace Abc;
using namespace AbcGeom;

AbcDynamicPaintWriter::AbcDynamicPaintWriter(AbcWriterArchive *archive, Object *ob, DynamicPaintSurface *surface) :
    DynamicPaintWriter(ob, surface, archive),
    AbcWriter(archive)
{
	if (archive->archive) {
	}
}

AbcDynamicPaintWriter::~AbcDynamicPaintWriter()
{
}

void AbcDynamicPaintWriter::write_sample()
{
	if (!archive()->archive)
		return;
}


AbcDynamicPaintReader::AbcDynamicPaintReader(AbcReaderArchive *archive, Object *ob, DynamicPaintSurface *surface) :
    DynamicPaintReader(ob, surface, archive),
    AbcReader(archive)
{
	if (archive->archive.valid()) {
		IObject root = archive->archive.getTop();
//		m_points = IPoints(root, m_psys->name);
	}
}

AbcDynamicPaintReader::~AbcDynamicPaintReader()
{
}

PTCReadSampleResult AbcDynamicPaintReader::read_sample(float frame)
{
	return PTC_READ_SAMPLE_INVALID;
}

/* ==== API ==== */

Writer *abc_writer_dynamicpaint(WriterArchive *archive, Object *ob, DynamicPaintSurface *surface)
{
	BLI_assert(dynamic_cast<AbcWriterArchive *>(archive));
	return new AbcDynamicPaintWriter((AbcWriterArchive *)archive, ob, surface);
}

Reader *abc_reader_dynamicpaint(ReaderArchive *archive, Object *ob, DynamicPaintSurface *surface)
{
	BLI_assert(dynamic_cast<AbcReaderArchive *>(archive));
	return new AbcDynamicPaintReader((AbcReaderArchive *)archive, ob, surface);
}

} /* namespace PTC */