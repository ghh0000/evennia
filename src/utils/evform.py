# coding=utf-8
"""
Mudform - a way to create advanced ascii forms

WARNING: UNDER DEVELOPMENT. Evform does currently NOT support
colour ANSI markers in the table. Non-colour forms should 
work fully (so make issues if they don't). 


This is intended for creating advanced ascii game forms, such as a
large pretty character sheet or info document.

The system works on the basis of a readin template that is given in a
separate python file imported into the handler. This file contains
some optional settings and a string mapping out the form. The template
has markers in it to denounce fields to fill. The markers map the
absolute size of the field and will be filled with an evtable.Cell
object when displaying the form.

Example of input file testform.py:

FORMCHAR = "x"
TABLECHAR = "c"

FORM = '''
.------------------------------------------------.
|                                                |
|  Name: xxxxx1xxxxx    Player: xxxxxxx2xxxxxxx  |
|        xxxxxxxxxxx                             |
|                                                |
 >----------------------------------------------<
|                                                |
| Desc:  xxxxxxxxxxx    STR: x4x    DEX: x5x     |
|        xxxxx3xxxxx    INT: x6x    STA: x7x     |
|        xxxxxxxxxxx    LUC: x8x    MAG: x9x     |
|                                                |
 >----------------------------------------------<
|          |                                     |
| cccccccc | ccccccccccccccccccccccccccccccccccc |
| cccccccc | ccccccccccccccccccccccccccccccccccc |
| cccAcccc | ccccccccccccccccccccccccccccccccccc |
| cccccccc | ccccccccccccccccccccccccccccccccccc |
| cccccccc | cccccccccccccccccBccccccccccccccccc |
|          |                                     |
`-----------------------------------------------´
'''

The first line of the FORM string is ignored. The forms and table
markers must mark out complete, unbroken rectangles, each containing
one embedded single-character identifier (so the smallest element
possible is a 3-character wide form). The identifier can be any
character except for the FORM_CHAR and TABLE_CHAR and some of the
common ascii-art elements, like space, _ | * etc (see
INVALID_FORMCHARS in this module). Form Rectangles can have any size,
but must be separated from each other by at least one other
character's width.

Use as follows:

    import mudform

    # create a new form from the template
    form = mudform.MudForm("path/to/testform.py")

    # add data to each tagged form cell
    form.map(cells={1: "Tom the Bouncer",
                    2: "Griatch",
                    3: "A sturdy fellow",
                    4: 12,
                    5: 10,
                    6:  5,
                    7: 18,
                    8: 10,
                    9:  3})
    # create the EvTables
    tableA = mudform.EvTable("HP","MV","MP",
                               table=[["**"], ["*****"], ["***"]],
                               border="incols")
    tableB = mudform.EvTable("Skill", "Value", "Exp",
                               table=[["Shooting", "Herbalism", "Smithing"],
                                      [12,14,9],["550/1200", "990/1400", "205/900"]],
                               border="incols")
    # add the tables to the proper ids in the form
    form.map(tables={"A": tableA,
                     "B": tableB}
    print form

This produces the following result:

.------------------------------------------------.
|                                                |
|  Name: Tom the        Player: Griatch          |
|        Bouncer                                 |
|                                                |
 >----------------------------------------------<
|                                                |
| Desc:  A sturdy       STR: 12     DEX: 10      |
|        fellow         INT: 5      STA: 18      |
|                       LUC: 10     MAG: 3       |
|                                                |
 >----------------------------------------------<
|          |                                     |
| HP|MV|MP | Skill      |Value      |Exp         |
| ~~+~~+~~ | ~~~~~~~~~~~+~~~~~~~~~~~+~~~~~~~~~~~ |
| **|**|** | Shooting   |12         |550/1200    |
|   |**|*  | Herbalism  |14         |990/1400    |
|   |* |   | Smithing   |9          |205/900     |
|          |                                     |
 `----------------------------------------------´

The marked forms have been replaced with Cells of text and with
EvTables. The form can be updated by simply re-applying form.map()
with the updated data.

When working with the template ascii file, you can use form.reload()
to re-read the template and re-apply all existing mappings.

Each component is restrained to the width and height specified by the
template, so it will resize to fit (or crop text if the area is too
small for it. If you try to fit a table into an area it cannot fit
into (when including its borders and at least one line of text), the
form will raise an error.

"""

import re
import copy
from src.utils.evtable import Cell, EvTable
from src.utils.utils import all_from_module, to_str, to_unicode

# non-valid form-identifying characters (which can thus be
# used as separators between forms without being detected
# as an identifier). These should be listed in regex form.

INVALID_FORMCHARS = r"\s\/\|\\\*\_\-\#\<\>\~\^\:\;\.\,"


class EvForm(object):
    """
    This object is instantiated with a text file and parses
    it for rectangular form fields. It can then be fed a
    mapping so as to populate the fields with fixed-width
    Cell or Tablets.


    """
    def __init__(self, filename=None, cells=None, tables=None, form=None, **kwargs):
        """
        Initiate the form

        keywords:
            filename - path to template file
            form - dictionary of {"CELLCHAR":char,
                                  "TABLECHAR":char,
                                  "FORM":templatestring}
                    if this is given, filename is not read.
            cells - a dictionary mapping of {id:text}
            tables -  dictionary mapping of {id:EvTable}

        other kwargs are fed as options to the Cells and EvTables
        (see evtablet.Cell and evtable.EvTable for more info).

        """
        self.filename = filename
        self.input_form_dict = form

        self.cells_mapping =  dict((str(key), value) for key, value in cells.items()) if cells  else {}
        self.tables_mapping = dict((str(key), value) for key, value in tables.items()) if tables else {}

        self.cellchar = "x"
        self.tablechar = "c"

        self.raw_form = []
        self.form = []

        # clean kwargs (these cannot be overridden)
        kwargs.pop("enforce_size", None)
        kwargs.pop("width", None)
        kwargs.pop("height", None)
        # table/cell options
        self.options = kwargs

        self.reload()

    def _parse_rectangles(self, cellchar, tablechar, form, **kwargs):
        """
        Parse a form for rectangular formfields identified by
        formchar enclosing an identifier.
        """

        # update options given at creation with new input - this
        # allows e.g. self.map() to add custom settings for individual
        # cells/tables
        custom_options = copy.copy(self.options)
        custom_options.update(kwargs)

        nform = len(form)

        mapping = {}
        cell_coords = {}
        table_coords = {}

        # Locate the identifier tags and the horizontal end coords for all forms
        re_cellchar =  re.compile(r"%s+([^%s%s])%s+" % (cellchar, INVALID_FORMCHARS, cellchar, cellchar))
        re_tablechar = re.compile(r"%s+([^%s%s|])%s+" % (tablechar, INVALID_FORMCHARS, tablechar, tablechar))
        for iy, line in enumerate(form):
            # find cells
            ix0 = 0
            while True:
                match = re_cellchar.search(line, ix0)
                if match:
                    # get the width of the rectangle directly from the match
                    cell_coords[match.group(1)] = [iy, match.start(), match.end()]
                    ix0 = match.end()
                else:
                    break
            # find tables
            ix0 = 0
            while True:
                match = re_tablechar.search(line, ix0)
                if match:
                    # get the width of the rectangle directly from the match
                    table_coords[match.group(1)] = [iy, match.start(), match.end()]
                    ix0 = match.end()
                else:
                    break
        #print "table_coords:", table_coords

        # get rectangles and assign Cells
        for key, (iy, leftix, rightix) in cell_coords.items():

            # scan up to find top of rectangle
            dy_up = 0
            if iy > 0:
                for i in range(1,iy):
                    #print "dy_up:", [form[iy-i][ix] for ix in range(leftix, rightix)]
                    if all(form[iy-i][ix] == cellchar for ix in range(leftix, rightix)):
                        dy_up += 1
                    else:
                        break
            # find bottom edge of rectangle
            dy_down = 0
            if iy < nform-1:
                for i in range(1,nform-iy-1):
                    #print "dy_down:", [form[iy+i][ix]for ix in range(leftix, rightix)]
                    if all(form[iy+i][ix] == cellchar for ix in range(leftix, rightix)):
                        dy_down += 1
                    else:
                        break

            #  we have our rectangle. Calculate size of Cell.
            iyup = iy - dy_up
            iydown = iy + dy_down
            width = rightix - leftix
            height = abs(iyup - iydown) + 1

            # we have all the coordinates we need. Create Cell.
            data = self.cells_mapping.get(key, "")
            #if key == "1":
            #print "creating cell '%s' (%s):" % (key, data)
            #print "iy=%s, iyup=%s, iydown=%s, leftix=%s, rightix=%s, width=%s, height=%s" % (iy, iyup, iydown, leftix, rightix, width, height)

            options = { "pad_left":0, "pad_right":0, "pad_top":0, "pad_bottom":0, "align":"l", "valign":"t", "enforce_size":True}
            options.update(custom_options)
            #if key=="4":
            #print "options:", options

            mapping[key] = (iyup, leftix, width, height, Cell(data, width=width, height=height,**options))

        # get rectangles and assign Tables
        for key, (iy, leftix, rightix) in table_coords.items():

            # scan up to find top of rectangle
            dy_up = 0
            if iy > 0:
                for i in range(1,iy):
                    #print "dy_up:", [form[iy-i][ix] for ix in range(leftix, rightix)]
                    if all(form[iy-i][ix] == tablechar for ix in range(leftix, rightix)):
                        dy_up += 1
                    else:
                        break
            # find bottom edge of rectangle
            dy_down = 0
            if iy < nform-1:
                for i in range(1,nform-iy-1):
                    #print "dy_down:", [form[iy+i][ix]for ix in range(leftix, rightix)]
                    if all(form[iy+i][ix] == tablechar for ix in range(leftix, rightix)):
                        dy_down += 1
                    else:
                        break

            #  we have our rectangle. Calculate size of Table.
            iyup = iy - dy_up
            iydown = iy + dy_down
            width = rightix - leftix
            height = abs(iyup - iydown) + 1

            # we have all the coordinates we need. Create Table.
            table = self.tables_mapping.get(key, None)
            #print "creating table '%s' (%s):" % (key, data)
            #print "iy=%s, iyup=%s, iydown=%s, leftix=%s, rightix=%s, width=%s, height=%s" % (iy, iyup, iydown, leftix, rightix, width, height)

            options = { "pad_left":0, "pad_right":0, "pad_top":0, "pad_bottom":0,
                        "align":"l", "valign":"t", "enforce_size":True}
            options.update(custom_options)
            #print "options:", options

            if table:
                table.reformat(width=width, height=height, **options)
            else:
                table = EvTable(width=width, height=height, **options)
            mapping[key] = (iyup, leftix, width, height, table)

        return mapping

    def _populate_form(self, raw_form, mapping):
        """
        Insert cell contents into form at given locations
        """
        form = copy.copy(raw_form)
        for key, (iy0, ix0, width, height, cell_or_table) in mapping.items():
            # rect is a list of <height> lines, each <width> wide
            rect = cell_or_table.get()
            for il, rectline in enumerate(rect):
                formline = form[iy0+il]
                # insert new content, replacing old
                form[iy0+il] = formline = formline[:ix0] + rectline + formline[ix0+width:]
        return form

    def map(self, cells=None, tables=None, **kwargs):
        """
        Add mapping for form.

        cells - a dictionary of {identifier:celltext}
        tables - a dictionary of {identifier:table}

        kwargs will be forwarded to tables/cells. See
        evtable.Cell and evtable.EvTable for info.

        """
        # clean kwargs (these cannot be overridden)
        kwargs.pop("enforce_size", None)
        kwargs.pop("width", None)
        kwargs.pop("height", None)

        new_cells =  dict((to_str(key), value) for key, value in cells.items()) if cells  else {}
        new_tables = dict((to_str(key), value) for key, value in tables.items()) if tables else {}

        self.cells_mapping.update(new_cells)
        self.tables_mapping.update(new_tables)
        self.reload()

    def reload(self, filename=None, form=None, **kwargs):
        """
        Creates the form from a stored file name
        """
        # clean kwargs (these cannot be overridden)
        kwargs.pop("enforce_size", None)
        kwargs.pop("width", None)
        kwargs.pop("height", None)

        if form or self.input_form_dict:
            datadict = form if form else self.input_form_dict
            self.input_form_dict = datadict
        elif filename or self.filename:
            filename = filename if filename else self.filename
            datadict = all_from_module(filename)
            self.filename = filename
        else:
            datadict = {}

        cellchar = to_str(datadict.get("FORMCHAR", "x"))
        self.cellchar = to_str(cellchar[0] if len(cellchar) > 1 else cellchar)
        tablechar = datadict.get("TABLECHAR", "c")
        self.tablechar = tablechar[0] if len(tablechar) > 1 else tablechar

        # split into a list of list of lines. Form can be indexed with form[iy][ix]
        self.raw_form = to_unicode(datadict.get("FORM", "")).split("\n")
        # strip first line
        self.raw_form = self.raw_form[1:] if self.raw_form else self.raw_form

        self.options.update(kwargs)

        # parse and replace
        self.mapping = self._parse_rectangles(self.cellchar, self.tablechar, self.raw_form, **kwargs)
        self.form = self._populate_form(self.raw_form, self.mapping)

    def __str__(self):
        "Prints the form"
        return "\n".join([to_str(line) for line in self.form])


